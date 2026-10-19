import time
import cv2
import subprocess
import argparse
import re
import sys
import threading
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO
import torch
import os
import math
import numpy as np
from tqdm import tqdm
import yt_dlp
import mediapipe as mp
# import whisper (replaced by faster_whisper inside function)
from google import genai
from google.genai import types as genai_types

import gemini_worker
import hook_grounding
import layout_picker
import llm_backend
import story_director
import pacing
import export_quality
import clip_selection
import clip_ranking
from clip_selection import (build_transcript_windows, clip_count_targets,
                            clip_duration_bounds, snap_clip_to_words,
                            trim_to_best)
from ffmpeg_utils import (video_encode_args, audio_encode_args, cut_clip, QUALITY,
                          QUALITY_FAST, METADATA_SCRUB)
from dotenv import load_dotenv
from framing_geometry import crop_size, crop_position, needs_context, subject_position
import json

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
ASPECT_RATIO = 9 / 16

GEMINI_PROMPT_TEMPLATE = """
You are a senior short-form video editor. Read the ENTIRE transcript and word-level timestamps to choose the 3–15 MOST VIRAL moments for TikTok/IG Reels/YouTube Shorts. Each clip must be between 15 and 60 seconds long.

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- Each clip between 15 and 60 s (inclusive).
- Prefer starting 0.2–0.4 s BEFORE the hook and ending 0.2–0.4 s AFTER the payoff.
- Use silence moments for natural cuts; never cut in the middle of a word or phrase.
- STRICTLY FORBIDDEN to use time formats other than absolute seconds.

VIDEO_DURATION_SECONDS: {video_duration}

TRANSCRIPT_TEXT (raw):
{transcript_text}

WORDS_JSON (array of {{w, s, e}} where s/e are seconds):
{words_json}

STRICT EXCLUSIONS:
- No generic intros/outros or purely sponsorship segments unless they contain the hook.
- No clips < 15 s or > 60 s.

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst). In the descriptions, ALWAYS include a CTA like "Follow me and comment X and I'll send you the workflow" (especially if discussing an n8n workflow):
{{
  "shorts": [
    {{
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words) with 1-2 fitting emojis. MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized... 😳', 'Did you know? 🤯', 'Stop doing this! 🚫'>"
    }}
  ]
}}
"""

# Load the YOLO model once (Keep for backup or scene analysis if needed)
# YOLO_MODEL_PATH lets deployments point at a pre-downloaded weights file so a
# volume mounted over the workdir doesn't trigger a re-download at startup.
model = YOLO(os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt"))

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

# Consecutive detections a large target move must survive before the camera
# follows it (see SmoothedCameraman.update_target). Env-overridable so the
# damping can be dialled back without a deploy; 1 restores the old behaviour.
JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "3")), 1)

# Reset the tracker and the cameraman's damping at every scene cut, so the
# first face found in the new shot is framed instantly instead of being treated
# as a suspicious "jump" from the previous shot's subject (see
# SmoothedCameraman.begin_scene). 0 restores the old behaviour.
SCENE_CUT_RESET = os.environ.get("SCENE_CUT_RESET", "1") != "0"


class SmoothedCameraman:
    """
    Handles smooth camera movement.
    Simplified Logic: "Heavy Tripod"
    Only moves if the subject leaves the center safe zone.
    Moves slowly and linearly.
    """
    def __init__(self, output_width, output_height, video_width, video_height, aspect_ratio=ASPECT_RATIO, fps=30.):
        self.motion_time_scale=30./max(1.,float(fps))
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height
        self.aspect_ratio = aspect_ratio

        # Initial State
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        self.current_center_y = self.target_center_y = video_height / 2

        # Calculate crop dimensions once
        self.crop_width, self.crop_height = crop_size(video_width, video_height, aspect_ratio)
             
        # Safe Zone: 20% of the video width
        # As long as the target is within this zone relative to current center, DO NOT MOVE.
        self.safe_zone_radius = self.crop_width * 0.25
        self.tracking_safe_zone_radius=self.safe_zone_radius

        # A target that teleports further than the safe zone in one detection is
        # far more often a detector error — a second face, a false positive, a
        # box snapping to a different body part — than a person who actually
        # moved that far. Committing to it immediately is what made the camera
        # swing: measured on real user footage, 22% of target updates jumped
        # more than the entire safe zone. So a big move has to REPEAT this many
        # times before the camera follows it; a wrong reading disappears on the
        # next detection and never moves the frame.
        #
        # The cost is latency on a genuinely fast move: at DETECT_STRIDE=4 and
        # 30fps, three confirmations is ~0.4s. That reads as an operator being
        # unhurried, which is the look we want, and it is far cheaper than the
        # whip-panning it replaces.
        #
        # Measured over 262s of TRACK footage from two real user videos
        # (26-jul-2026), confirm=1 -> 3: in-scene reversals 0.41/s -> 0.13/s
        # (-69%), camera travel 91px/s -> 60px/s (-34%). Per scene, 54 of 84 get
        # calmer and 23 are unchanged — but 7 get BUSIER, up to 59 -> 108px/s,
        # because committing later can leave the camera further to travel. Net
        # strongly positive, not universally so.
        self.jump_confirm_frames = JUMP_CONFIRM_FRAMES
        self._pending_target = None
        self._pending_count = 0
        self._snap_pending = False

    def begin_scene(self):
        """Forget the previous shot's subject at a scene cut.

        The jump damping above exists to reject detector noise INSIDE a shot.
        Across a cut it does the opposite of what is wanted: the new shot's face
        is (by construction) far from the old target, so it was held back for
        JUMP_CONFIRM_FRAMES detections and the camera then panned towards it at
        pan speed. On a real two-camera podcast (24-aug-2026) that showed up as
        a headless torso for 1.5s after every cut while the frame slid over to
        the speaker. The snap at the scene's first frame did not help: the
        target it snapped to was still the previous shot's.

        So: drop any pending jump, and cut (rather than pan) to the first target
        accepted in the new shot.
        """
        self._pending_target = None
        self._pending_count = 0
        self._snap_pending = True
        self.tracking_safe_zone_radius=self.safe_zone_radius
        if os.getenv('SMART_REFRAME', '1') != '0':
            # With no detection in the new scene, use its centre rather than
            # carrying the previous speaker's off-centre crop across the cut.
            self.current_center_x = self.target_center_x = self.video_width / 2
            self.current_center_y = self.target_center_y = self.video_height / 2

    def update_target(self, face_box):
        """Update the target centre from a detection, ignoring lone big jumps."""
        if not face_box:
            return
        x, y, w, h = face_box
        if (not all(math.isfinite(float(v)) for v in face_box) or w <= 0 or h <= 0):
            return
        new_center = x + w / 2
        new_center = max(0, min(new_center, self.video_width))
        # Only tall inputs have vertical travel. Text reserves never move faces.
        _,top=subject_position(self.video_width,self.video_height,self.crop_width,self.crop_height,
                              (new_center,y+h/2,w,h))
        new_y=top+self.crop_height/2
        self.tracking_safe_zone_radius=min(self.safe_zone_radius,max(0,self.crop_width/2-w/2-self.crop_width*.08))

        if self._snap_pending:
            self._snap_pending = False
            self._pending_target = None
            self._pending_count = 0
            self.target_center_x = new_center
            self.current_center_x = new_center
            self.current_center_y = self.target_center_y = new_y
            return

        if abs(new_center - self.target_center_x) > self.safe_zone_radius:
            # Same big move as last time? Count it. Otherwise start counting
            # afresh — two contradictory outliers must not confirm each other.
            if (self._pending_target is not None
                    and abs(new_center - self._pending_target) <= self.safe_zone_radius):
                self._pending_count += 1
            else:
                self._pending_target = new_center
                self._pending_count = 1
            if self._pending_count < self.jump_confirm_frames:
                return  # not convinced yet — hold the frame

        self._pending_target = None
        self._pending_count = 0
        self.target_center_x = new_center
        self.target_center_y = new_y
    
    def get_crop_box(self, force_snap=False):
        """
        Returns the (x1, y1, x2, y2) for the current frame.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
            self.current_center_y = self.target_center_y
        else:
            diff = self.target_center_x - self.current_center_x
            
            # SIMPLIFIED LOGIC:
            # 1. Is the target outside the safe zone?
            if abs(diff) > self.tracking_safe_zone_radius:
                # 2. If yes, move towards it slowly (Linear Speed)
                # Determine direction
                direction = 1 if diff > 0 else -1
                
                # Speed: 2 pixels per frame (Slow pan)
                # If the distance is HUGE (scene change or fast movement), speed up slightly
                if abs(diff) > self.crop_width * 0.5:
                    speed = self.crop_width * .025 # resolution-independent fast reframe
                else:
                    speed = self.crop_width * .005  # Slow, steady pan
                
                self.current_center_x += direction * min(abs(diff), speed*self.motion_time_scale)
                
                # Check if we overshot (prevent oscillation)
                new_diff = self.target_center_x - self.current_center_x
                if (direction == 1 and new_diff < 0) or (direction == -1 and new_diff > 0):
                    self.current_center_x = self.target_center_x
            
            # If inside safe zone, DO NOTHING (Stationary Camera)
                
        # Clamp center
        half_crop = self.crop_width / 2
        
        if self.current_center_x - half_crop < 0:
            self.current_center_x = half_crop
        if self.current_center_x + half_crop > self.video_width:
            self.current_center_x = self.video_width - half_crop
            
        x1 = int(self.current_center_x - half_crop)
        x2 = int(self.current_center_x + half_crop)
        
        x1 = max(0, x1)
        x2 = min(self.video_width, x2)
        
        if os.getenv('SMART_REFRAME', '1') != '0':
            diff_y = self.target_center_y - self.current_center_y
            if abs(diff_y) > self.crop_height * .08:
                self.current_center_y += max(-self.crop_height * .015*self.motion_time_scale,
                                             min(diff_y, self.crop_height * .015*self.motion_time_scale))
        x1, y1 = crop_position(self.video_width, self.video_height,
                               self.crop_width, self.crop_height,
                               self.current_center_x, self.current_center_y)
        return x1, y1, x1 + self.crop_width, y1 + self.crop_height

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary obstructions.
    """
    def __init__(self, stabilization_frames=15, cooldown_frames=30, fps=30.):
        self.max_missing_frames=max(1,round(fps))
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: score}
        self.last_seen = {}       # {id: frame_number}
        self.locked_counter = 0   # How long we've been locked on current speaker
        
        # Hyperparameters
        self.stabilization_threshold = stabilization_frames # Frames needed to confirm a new speaker
        self.switch_cooldown = cooldown_frames              # Minimum frames before switching again
        self.last_switch_frame = -1000
        
        # ID tracking
        self.next_id = 0
        self.known_faces = [] # [{'id': 0, 'center': x, 'last_frame': 123}]

    def reset(self):
        """Forget every speaker at a scene cut.

        Identity, hysteresis and the switch cooldown are all about continuity
        within a shot. After a cut none of it applies: the sticky x3 bonus and
        the cooldown were holding the previous shot's speaker (returning None)
        for up to 30 frames while a new face sat unframed.
        """
        self.active_speaker_id = None
        self.speaker_scores = {}
        self.last_seen = {}
        self.locked_counter = 0
        self.last_switch_frame = -1000
        self.known_faces = []

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.
        face_candidates: list of {'box': [x,y,w,h], 'score': float}
        """
        from framing_geometry import associate_faces
        current_candidates, self.known_faces, self.next_id = associate_faces(
            face_candidates, self.known_faces, frame_number, width,
            self.next_id, ttl=self.max_missing_frames)
        alive={k['id'] for k in self.known_faces}
        self.speaker_scores={pid:score for pid,score in self.speaker_scores.items() if pid in alive}

        # 2. Update Scores with decay
        for pid in list(self.speaker_scores.keys()):
             self.speaker_scores[pid] *= 0.85 # Faster decay (was 0.9)
             if self.speaker_scores[pid] < 0.1:
                 del self.speaker_scores[pid]

        # Add new scores
        for cand in current_candidates:
            pid = cand['id']
            # Score is purely based on size (proximity) now that we don't have mouth
            raw_score = cand['score'] / (width * width * 0.05)
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + raw_score

        # 3. Determine Best Speaker
        if not current_candidates:
            # If no one found, maintain last active speaker if cooldown allows
            # to avoid black screen or jump to 0,0
            return None 
            
        best_candidate = None
        max_score = -1
        
        for cand in current_candidates:
            pid = cand['id']
            total_score = self.speaker_scores.get(pid, 0)
            
            # Hysteresis: HUGE Bonus for current active speaker
            if pid == self.active_speaker_id:
                total_score *= 3.0 # Sticky factor
                
            if total_score > max_score:
                max_score = total_score
                best_candidate = cand

        # 4. Decide Switch
        if best_candidate:
            target_id = best_candidate['id']
            
            if target_id == self.active_speaker_id:
                self.locked_counter += 1
                return best_candidate['box']
            
            # New person. The cooldown must hold whether or not the current
            # speaker happens to be detected in THIS frame.
            #
            # It used to fall through and switch when the active speaker was
            # missing from the candidate list — a blink, a head turn or one
            # motion-blurred frame was enough. That is precisely when the
            # cooldown is needed, so it only ever fired when it wasn't: 3 of 7
            # target switches measured on a 12s clip (25-jul-2026) jumped the
            # cooldown this way, and every jump drags the camera across frame.
            #
            # Returning None holds instead: the caller only calls
            # update_target() on a truthy box, so the camera keeps its current
            # target and finishes whatever move it was making. The hold is
            # bounded by the cooldown itself — once it expires, a speaker who
            # really did leave the shot is switched away from normally.
            if frame_number - self.last_switch_frame < self.switch_cooldown:
                old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
                return old_cand['box'] if old_cand else None

            self.active_speaker_id = target_id
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return best_candidate['box']
            
        return None

# Detectors never need full-resolution frames: MediaPipe returns relative
# coords and YOLO boxes are scaled back up. Running them on a ≤640px copy cuts
# per-frame preprocessing cost hard, which is what dominates CPU-only renders.
DETECT_MAX_WIDTH = 640
# The global MediaPipe graph and YOLO model are NOT thread-safe; clips render
# in parallel, so every inference goes through this lock. Contention is small
# (a few ms per call) — the ffmpeg renders are where the parallel time goes.
DETECT_LOCK = threading.Lock()
# Detect every Nth frame; SmoothedCameraman interpolates between updates.
DETECT_STRIDE = max(int(os.environ.get("DETECT_STRIDE", "4")), 1)
# YOLO fallback (no face found) is far heavier than MediaPipe — extra throttle.
YOLO_FALLBACK_STRIDE = DETECT_STRIDE * 2


def _detection_frame(frame):
    """Downscaled copy for detectors. Returns (small_frame, scale) with
    scale mapping small-frame pixel coords back to the original frame."""
    h, w = frame.shape[:2]
    if w <= DETECT_MAX_WIDTH:
        return frame, 1.0
    scale = w / DETECT_MAX_WIDTH
    small = cv2.resize(frame, (DETECT_MAX_WIDTH, max(int(h / scale), 2)),
                       interpolation=cv2.INTER_AREA)
    return small, scale


def detect_face_candidates(frame):
    """
    Returns list of all detected faces using lightweight FaceDetection.
    Boxes are in ORIGINAL frame coordinates (detection runs downscaled;
    MediaPipe's relative coords make the mapping exact).
    """
    height, width, _ = frame.shape
    small, _scale = _detection_frame(frame)
    rgb_frame = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    with DETECT_LOCK:
        results = face_detection.process(rgb_frame)
    
    candidates = []
    
    if not results.detections:
        return []
        
    for detection in results.detections:
        bboxC = detection.location_data.relative_bounding_box
        x = int(bboxC.xmin * width)
        y = int(bboxC.ymin * height)
        w = int(bboxC.width * width)
        h = int(bboxC.height * height)
        
        candidates.append({
            'box': [x, y, w, h],
            'score': w * h # Area as score
        })
            
    return candidates

def detect_portrait_candidates(frame):
    """Use existing person detections when hats/profiles hide every face.

    Upper-person regions are framing anchors, not detected faces or identified
    speakers. Several substantial people remain separate to preserve context.
    """
    faces=detect_face_candidates(frame)
    if faces:return faces
    try:
        regions=[r['box'] for r in detect_framing_regions(frame) if r['label']=='person']
        largest=max((w*h for x,y,w,h in regions),default=0)
        return [dict(box=[x+w*.2,y,w*.6,h*.35],score=w*h*.21,body_anchor=True)
                for x,y,w,h in regions if w*h>=largest*.35]
    except Exception:
        return []  # Optional subject detection retains the normal wide fallback.


def detect_person_yolo(frame):
    """
    Fallback: Detect largest person using YOLO when face detection fails.
    Returns [x, y, w, h] of the person's 'upper body' approximation, in
    ORIGINAL frame coordinates (inference runs on a downscaled copy).
    """
    small, scale = _detection_frame(frame)
    # Use the globally loaded model
    with DETECT_LOCK:
        results = model(small, verbose=False, classes=[0]) # class 0 is person

    if not results:
        return None

    best_box = None
    max_area = 0

    for result in results:
        boxes = result.boxes
        for box in boxes:
            x1, y1, x2, y2 = [int(i * scale) for i in box.xyxy[0]]
            w = x2 - x1
            h = y2 - y1
            area = w * h
            
            if area > max_area:
                max_area = area
                # Focus on the top 40% of the person (head/chest) for framing
                # This approximates where the face is if we can't detect it directly
                face_h = int(h * 0.4)
                best_box = [x1, y1, w, face_h]
                
    return best_box


def detect_framing_regions(frame):
    """Reuse the loaded YOLO model for full bodies and explicit object classes.

    A COCO label is not proof of narrative importance. Configured action/screen
    objects are conservatively preserved when a face crop would hide them.
    Unsupported classes (e.g. treadmill/supermarket shelves in COCO) are never
    invented; wide/no-face shots already retain their full context.
    """
    requested={v.strip().lower() for v in os.getenv('REFRAME_OBJECT_CLASSES',
        'bicycle,sports ball,skateboard,surfboard,tennis racket,laptop,tv').split(',') if v.strip()}
    names=getattr(model,'names',{})
    if isinstance(names,list):names=dict(enumerate(names))
    classes=[int(i) for i,name in names.items() if str(name).lower() in requested|{'person'}]
    if not classes:return []
    small,scale=_detection_frame(frame)
    with DETECT_LOCK:results=model(small,verbose=False,classes=classes,conf=.55)
    height,width=frame.shape[:2];regions=[]
    for result in results or []:
        for box in result.boxes:
            x1,y1,x2,y2=[float(v)*scale for v in box.xyxy[0]]
            x1=max(0,min(width-1,x1));y1=max(0,min(height-1,y1))
            x2=max(x1+1,min(width,x2));y2=max(y1+1,min(height,y2))
            label=str(names.get(int(box.cls[0]),'')).lower()
            area=(x2-x1)*(y2-y1)
            if label=='person':
                if x2-x1<width*.045 or y2-y1<height*.25:continue
            elif area<width*height*.015:continue
            regions.append(dict(box=[x1,y1,x2-x1,y2-y1],label=label,confidence=float(box.conf[0])))
    return regions[:32]

def create_general_frame(frame, output_width, output_height):
    """
    Creates a 'General Shot' frame: 
    - Background: Blurred zoom of original
    - Foreground: Entire original image fitted and centered in the output.
    """
    orig_h, orig_w = frame.shape[:2]
    
    # 1. Background (cover both dimensions without stretching)
    # Crop center to aspect ratio
    bg_scale = max(output_width / orig_w, output_height / orig_h)
    bg_w = max(output_width, int(round(orig_w * bg_scale)))
    bg_h = max(output_height, int(round(orig_h * bg_scale)))
    bg_resized = cv2.resize(frame, (bg_w, bg_h), interpolation=cv2.INTER_LINEAR)

    # Crop center of background
    start_x = (bg_w - output_width) // 2
    if start_x < 0: start_x = 0
    start_y = (bg_h - output_height) // 2
    background = bg_resized[start_y:start_y+output_height, start_x:start_x+output_width]
    if background.shape[1] != output_width:
        background = cv2.resize(background, (output_width, output_height), interpolation=cv2.INTER_LINEAR)

    # Blur at one-eighth resolution, then scale up and dim the background.
    # The clear foreground below stays untouched.
    small_bg = cv2.resize(background, (max(output_width // 8, 2), max(output_height // 8, 2)),
                          interpolation=cv2.INTER_AREA)
    from framing_geometry import blur_strength
    small_bg = cv2.GaussianBlur(small_bg, (0, 0), max(1.,blur_strength()*small_bg.shape[1]/1080))
    gray=cv2.cvtColor(small_bg,cv2.COLOR_BGR2GRAY)[:,:,None]
    small_bg=np.clip((small_bg*.7+gray*.3)-15.3,0,255).astype(np.uint8)
    background = cv2.resize(small_bg, (output_width, output_height),
                            interpolation=cv2.INTER_LINEAR)

    # 2. Foreground (contain the whole image)
    scale = min(output_width / orig_w, output_height / orig_h)
    fg_w = max(1, min(output_width, int(round(orig_w * scale))))
    fg_h = max(1, min(output_height, int(round(orig_h * scale))))
    foreground = cv2.resize(frame, (fg_w, fg_h), interpolation=cv2.INTER_LINEAR)

    # 3. Overlay
    y_offset = (output_height - fg_h) // 2

    # Clone background to avoid modifying it
    final_frame = background.copy()
    x_offset = (output_width - fg_w) // 2
    final_frame[y_offset:y_offset+fg_h, x_offset:x_offset+fg_w] = foreground
    
    return final_frame


def create_editorial_frame(frame, output_width, output_height):
    """Frame-loop fallback for the detail + context landscape layout."""
    from reframe_v2 import editorial_geometry
    orig_h, orig_w = frame.shape[:2]
    crop_w, crop_h, x, y, detail_h, context_h = editorial_geometry(
        orig_w, orig_h, output_width, output_height)
    detail = cv2.resize(frame[y:y+crop_h, x:x+crop_w],
                        (output_width, detail_h), interpolation=cv2.INTER_LINEAR)
    context = cv2.resize(frame, (output_width, context_h),
                         interpolation=cv2.INTER_LINEAR)
    context[:3, :] = (25, 25, 25)
    return np.vstack((detail, context))

# NOTE: a "route text-heavy scenes to GENERAL" rule was tried here and removed
# on 26-jul-2026. The problem it targets is real — a screencast that happens to
# contain one face gets cropped to the face and its headlines come out cut
# mid-word — but edge density is the wrong signal for it. Measured: a
# constructed talking-head-beside-a-chart scored 0.012 while the SAME shot
# without the panels scored 0.029, because a flat panel of text has far fewer
# edges than ordinary scene detail. Canny measures visual busyness, not text.
# A real fix needs an actual text detector (MSER/EAST) validated against clips
# that contain the failure mode; this corpus has almost none.


def analyze_scenes_strategy(video_path, scenes, aspect_ratio=ASPECT_RATIO):
    """
    Analyzes each scene to determine if it should be TRACK (Single person) or GENERAL (Group/Wide).
    Returns list of strategies corresponding to scenes.
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []

    if not cap.isOpened():
        return ['TRACK'] * len(scenes)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
        s_f, e_f = start.get_frames(), end.get_frames()
        # Sample 5 frames spread across the scene, clamped inside it (the old
        # start+5/end-5 samples landed outside scenes shorter than ~10 frames).
        margin = min(2, max(0, (e_f - s_f - 1) // 2))
        frames_to_check = sorted(set(
            int(round(f)) for f in np.linspace(s_f + margin, e_f - 1 - margin, 5)
        ))

        face_counts = []
        dominant_samples = []
        context_samples = []
        for f_idx in frames_to_check:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret: continue

            # Near-black frames (fades, cut-to-black) carry no faces and used
            # to drag single-person scenes into GENERAL. Skip them.
            if frame.mean() < 16:
                continue

            # Detect faces
            candidates = (detect_portrait_candidates(frame) if
                __import__('video_templates').framing_preference()=='auto' else detect_face_candidates(frame))
            import split_layout
            candidates = split_layout.dedupe_faces(candidates)
            face_counts.append(len(candidates))
            context_samples.append(needs_context(candidates, frame.shape[1],
                                                   frame.shape[0], aspect_ratio))
            areas = sorted((c['box'][2]*c['box'][3] for c in candidates), reverse=True)
            dominant_samples.append(bool(areas) and (len(areas)==1 or areas[0] >= 1.8*areas[1]))

        # Decision Logic
        if not face_counts:
            avg_faces = 0
        else:
            avg_faces = sum(face_counts) / len(face_counts)

        # Strategy:
        # 0 faces -> GENERAL (Landscape/B-roll)
        # 1 face -> TRACK
        # > 1.2 faces -> GENERAL (Group)

        dominant = dominant_samples and sum(dominant_samples)/len(dominant_samples) >= .6
        preserve = context_samples and sum(context_samples)/len(context_samples) >= .4
        automatic=__import__('video_templates').framing_preference()=='auto'
        if preserve and os.getenv('SMART_REFRAME', '1') != '0':
            strategies.append('GENERAL')
        elif __import__('video_templates').framing_preference() in ("subject", "editorial") and dominant and avg_faces >= .5:
            strategies.append('TRACK')
        elif automatic and avg_faces>=.5 and not preserve:
            # Nearby people can share a portrait crop. Headcount alone is not
            # evidence that a wide/blurred composition is necessary.
            strategies.append('TRACK')
        elif avg_faces > 1.2 or avg_faces < 0.5:
            strategies.append('GENERAL')
        else:
            strategies.append('TRACK')

    cap.release()

    # Hysteresis: a short scene whose two neighbors agree on the opposite
    # strategy is almost always a sampling miss (profile face, insert shot).
    # Each TRACK<->GENERAL flip is a full on-screen layout change, so flapping
    # is worse than an occasional wrong-but-stable choice.
    max_flip_frames = int(2.0 * fps)
    for i in range(1, len(strategies) - 1):
        dur = scenes[i][1].get_frames() - scenes[i][0].get_frames()
        # Never turn an independently classified wide/no-face insert into a
        # tight crop merely because the shots on either side contain a face.
        if (not automatic and dur < max_flip_frames and strategies[i] == 'TRACK'
                and strategies[i - 1] == strategies[i + 1] != strategies[i]):
            strategies[i] = strategies[i - 1]

    return strategies

def detect_scenes(video_path):
    import scene_detection
    return scene_detection.detect_scenes(video_path)

def get_video_resolution(video_path):
    probe = cv2.VideoCapture(video_path)
    try:
        if not probe.isOpened():
            raise IOError(f"cannot open video: {video_path}")
        return (int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        probe.release()


# Byte budget for the sanitized video title used as the stem of every derived
# file. Filesystems cap a name in BYTES (255 on ext4), not characters, and the
# pipeline decorates this stem: "_clip_10.mp4" (12), "subtitled_<ts>_" (21),
# "hooked_<ts>_" (18), "temp_hook_<hex8>_" (19), "autosubs_<ts>_" + ".ass" (24).
# Budgeting 120 bytes leaves room for all of them stacked (worst chain:
# subtitled_<ts>_hooked_<ts>_<stem>_clip_NN.mp4 ≈ 171 bytes) under the limit.
#
# The old cap was 100 CHARACTERS, which is 300 bytes of Bengali or Arabic — over
# the limit before any decoration. It surfaced as OSError 36 killing the hook
# endpoint in prod on 26-jul-2026.
MAX_TITLE_BYTES = 120


def truncate_bytes(text, max_bytes):
    """Trim ``text`` to a byte budget without splitting a multi-byte character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore")


def sanitize_filename(filename):
    """Remove invalid characters from filename and bound it for the filesystem."""
    # "canción" has two Unicode spellings: a precomposed ó (NFC) or an o plus a
    # combining acute (NFD). yt-dlp hands over titles in either, and the name
    # becomes the clip file, the R2 key and the URL path. Measured 24-ago-2026:
    # a key carrying the combining form is fetchable by a <video> element but a
    # fetch() of the same URL comes back 503, which broke the download button on
    # every clip with a Spanish title. Normalising here fixes the whole chain at
    # its source, and is a no-op for the ASCII names that already worked.
    filename = unicodedata.normalize('NFC', filename)
    filename = re.sub(r'[<>:"/\\|?*#]', '', filename)
    filename = filename.replace(' ', '_')
    return truncate_bytes(filename, MAX_TITLE_BYTES)


def is_youtube_url(url):
    """True for the hosts the proxy chain exists for. Anything else (a CDN
    mp4, tmpfiles/catbox, an R2 link) has no IP ban to dodge and downloads
    5-10x faster from the server's own IP than through the ISP proxies."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True
    return host.endswith(("youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com"))


def plan_download_attempts(direct_first, statics, paid, have_hd, youtube=True):
    """Ordered (label, capped, proxy) download plan — pure, unit-tested.

    ``youtube=False`` (a direct file URL): the server's own IP first, then one
    static proxy as the only fallback; the paid per-GB proxy is never used.

    Cheapest bandwidth first: the server's own IP, then the flat-rate static
    ISP proxies (uncapped 1080p, free bytes), then the per-GB paid proxy
    (720p cost cap), and last the conservative fallback strategy through the
    paid proxy (or a static/direct when no paid proxy is configured).
    ``capped`` marks attempts whose bytes are billed per GB."""
    if not youtube:
        plan = [('direct', False, None)]
        if statics:
            plan.append(('static-fallback', False, statics[0]))
        return plan
    plan = []
    if direct_first:
        plan.append(('HD-direct', False, None))
    if have_hd:
        for i, s in enumerate(statics):
            plan.append((f'HD-static{i + 1}', False, s))
    if statics and paid:
        # The conservative clients (tv_embed/android) through a FREE static,
        # before any per-GB attempt: YouTube serves a fake "Video unavailable"
        # to the web/HD client from datacenter-ISP ranges on some videos while
        # the fallback clients pass on the very same IPs (verified 4-sep-2026,
        # all three statics, three countries). Costs nothing and the paid path
        # was capped to 720p anyway, so there is no quality trade.
        plan.append(('fallback-static', False, statics[0]))
    if have_hd:
        plan.append(('HD', bool(paid), paid))
    plan.append(('fallback', bool(paid),
                 paid if paid else (statics[0] if statics else None)))
    return plan


def cap_source_duration(input_video, max_minutes):
    """Cut ``input_video`` down to its first ``max_minutes`` minutes, in place.

    Set through ``MAX_SOURCE_MINUTES`` by app.py when the user accepted the
    quota wall's "clip the first N minutes" offer: only N minutes were
    reserved, so nothing downstream may see more of the source than that.
    Cutting the file itself (rather than passing a window around) keeps every
    later stage byte-identical: transcription, the layout picker, the clip
    editor's re-renders and ``/api/source`` all read the same path. A source
    already within the cap is left untouched.

    Stream copy first (seconds, no quality loss; the cut lands on a packet
    boundary a fraction of a second past N). If the container refuses a copy
    the fallback re-encodes, which is slow but rare.
    """
    try:
        secs = float(max_minutes) * 60.0
    except (TypeError, ValueError):
        return input_video
    if secs <= 0:
        return input_video
    duration = 0.0
    try:
        cap = cv2.VideoCapture(input_video)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        duration = (int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / fps) if fps else 0.0
        cap.release()
    except Exception:
        duration = 0.0
    if duration and duration <= secs + 1.0:
        return input_video
    root, ext = os.path.splitext(input_video)
    tmp = f"{root}.capped{ext or '.mp4'}"
    attempts = [
        ["-c", "copy"],
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"],
    ]
    for codec_args in attempts:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", input_video,
               "-t", f"{secs:.3f}", *codec_args, "-movflags", "+faststart", tmp]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
            os.replace(tmp, input_video)
            shown = f"{int(math.ceil(duration / 60))}" if duration else "?"
            print(f"✂️ Clipping the first {float(max_minutes):g} min of {shown}: "
                  f"that is what the plan's remaining minutes cover.")
            return input_video
        except Exception as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            print(f"⚠️ Could not cut the source to {float(max_minutes):g} min "
                  f"({' '.join(codec_args[:2])}): {str(e)[:200]}")
    raise RuntimeError(f"could not cut the source to its first {float(max_minutes):g} minutes")


def download_youtube_video(url, output_dir="."):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    # SSRF guard: block non-http(s) schemes and private/loopback/metadata hosts
    # before handing the URL to yt-dlp.
    from security_utils import assert_public_url
    assert_public_url(url)
    # Throwaway hosts agents fall back to (tmpfiles.org) hand out short-lived
    # signed links; refresh through the host's page so yt-dlp gets the file.
    import file_hosts
    url = file_hosts.resolve(url)
    # Cloud mode rejects these at the probe; this is the self-host path.
    from yt_clients import NotASingleVideo, youtube_non_video_reason
    reason = youtube_non_video_reason(url)
    if reason:
        raise NotASingleVideo(f"This link is {reason}.")

    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()

    cookies_path = None
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        print("🍪 Found YOUTUBE_COOKIES env var, creating cookies file inside container...")
        try:
            import tempfile, atexit
            fd, cookies_path = tempfile.mkstemp(prefix='clip_cookies_', suffix='.txt')
            atexit.register(lambda p=cookies_path: os.path.exists(p) and os.remove(p))
            with os.fdopen(fd, 'w') as f:
                f.write(cookies_env)
            if os.path.exists(cookies_path):
                 # Never print file CONTENT here: with a headerless cookies
                 # blob this would leak live YouTube session cookies to logs.
                 print(f"   Debug: Cookies file created. Size: {os.path.getsize(cookies_path)} bytes")
        except Exception as e:
            print(f"⚠️ Failed to write cookies file: {e}")
            cookies_path = None
    else:
        cookies_path = None
        print("⚠️ YOUTUBE_COOKIES env var not found.")
    
    # Optional HTTP proxy. Set PROXY_URL to route downloads through it; unset
    # (self-host) goes direct as before.
    _proxy = os.environ.get("PROXY_URL", "").strip() or None
    if _proxy:
        print("🌐 Using proxy for download.")

    # Flat-rate static ISP proxies (STATIC_PROXY_URLS, comma-separated), tried
    # BEFORE the per-GB proxy: dedicated IPs with unlimited traffic, so their
    # bandwidth costs nothing per job and carries no 720p cost cap. Rotated per
    # job to spread load (and YouTube's attention) across the pool. PROXY_URL
    # stays the paid last resort — with STATIC_PROXY_URLS unset the behavior is
    # byte-identical to before.
    _statics = [p.strip() for p in
                os.environ.get("STATIC_PROXY_URLS", "").split(",") if p.strip()]
    if _statics:
        import random as _random
        k = _random.randrange(len(_statics))
        _statics = _statics[k:] + _statics[:k]
        print(f"🌐 {len(_statics)} static ISP proxies configured.")

    # Two download strategies, tried in order so a break in the HD path degrades
    # gracefully instead of failing the whole job: an HD attempt first, then a
    # conservative fallback (also the only strategy for self-host).
    _bgutil_http = os.environ.get("BGUTIL_BASE_URL", "").strip()
    _bgutil_script = os.environ.get("BGUTIL_SCRIPT_PATH", "").strip()
    # Client lists live in yt_clients.py (shared with the duration probe):
    # explicit `default,mweb` because the authed defaults alone return
    # "Video unavailable" on a share of videos, from every IP, and that was
    # what fed the per-GB proxy (6-sep-2026, verified in the prod container).
    from yt_clients import hd_extractor_args, fallback_extractor_args
    hd_args = hd_extractor_args(_bgutil_http, _bgutil_script)
    fallback_args = fallback_extractor_args(_bgutil_http, _bgutil_script)

    # Cap at 720p ONLY when the bytes actually go through the PER-GB paid proxy
    # — that cap exists to control bandwidth cost, and the direct attempt and
    # the flat-rate static proxies have none.
    #
    # This is per-attempt on purpose. Deciding it once from `_proxy` capped the
    # DIRECT attempt too, so with DIRECT_FIRST=1 (which serves most downloads)
    # every YouTube source arrived at 720p and, since the reframe inherits the
    # source height, 80% of delivered clips came out 406x720 (audited 25-jul-2026).
    def _hd_fmt_for(capped):
        if capped:
            return ('bestvideo[vcodec^=avc1][height<=720][ext=mp4]+bestaudio[ext=m4a]/'
                    'bestvideo[vcodec^=avc1][height<=720]+bestaudio/'
                    'best[height<=720][ext=mp4]/best[height<=720]/best')
        return ('bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[vcodec^=avc1][height<=1080]+bestaudio/'
                'best[height<=1080][ext=mp4]/best[ext=mp4]/best')

    def _base_opts(extractor_args, proxy, cookies=True):
        return {
            'quiet': False, 'verbose': True, 'no_warnings': False,
            'cookiefile': cookies_path if (cookies and cookies_path) else None,
            'proxy': proxy, 'socket_timeout': 30, 'retries': 10, 'fragment_retries': 10,
            'nocheckcertificate': True, 'cachedir': False,
            # A `watch?v=X&list=...` link is the one video the user was
            # watching, not the playlist: without this yt-dlp downloads every
            # entry of the list into the SAME outtmpl (the title is the
            # playlist's), paying for all of them and keeping the last.
            'noplaylist': True,
            'extractor_args': extractor_args,
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
            },
        }

    # Wire bytes actually pulled through the (paid) proxy, summed across
    # fragments/streams. Reported to app.py via the PROXY_BYTES= line below.
    _dl_bytes = {"total": 0, "partial": 0}

    def _progress_hook(d):
        if d.get('status') == 'downloading':
            # Bytes of a fragment still in flight: a failed attempt has
            # already paid for these even though 'finished' never fires.
            _dl_bytes["partial"] = int(d.get('downloaded_bytes') or 0)
        elif d.get('status') == 'finished':
            _dl_bytes["partial"] = 0
            _dl_bytes["total"] += int(d.get('total_bytes')
                                      or d.get('total_bytes_estimate')
                                      or d.get('downloaded_bytes') or 0)

    def _attempt(extractor_args, fmt, proxy, cookies=True):
        _dl_bytes["total"] = 0
        _dl_bytes["partial"] = 0
        with yt_dlp.YoutubeDL(_base_opts(extractor_args, proxy, cookies)) as ydl:
            info = ydl.extract_info(url, download=False)
        sanitized = sanitize_filename(info.get('title', 'youtube_video'))
        expected = os.path.join(output_dir, f'{sanitized}.mp4')
        if os.path.exists(expected):
            os.remove(expected)
        dl_opts = {
            **_base_opts(extractor_args, proxy, cookies),
            'format': fmt,
            'outtmpl': os.path.join(output_dir, f'{sanitized}.%(ext)s'),
            'merge_output_format': 'mp4', 'overwrites': True,
            'progress_hooks': [_progress_hook],
        }
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
        return sanitized

    # DIRECT_FIRST=1: try the server's own IP before spending proxy bandwidth.
    # Needs cookies + a PO-token provider — without both, YouTube flags the
    # datacenter IP after the first request (verified in prod, 21-jul-2026).
    _direct_first = (os.environ.get("DIRECT_FIRST", "").strip() == "1"
                     and (_proxy or _statics) and hd_args and cookies_path)

    # A fallback attempt runs anonymously when an HD attempt (with cookies)
    # already failed on the same route: the account cookies are what narrows
    # yt-dlp to the clients that die with "Video unavailable", and the
    # anonymous defaults were measured at 1080p on the same static IP. With
    # no HD path at all (self-host without a PO token provider) the fallback
    # is the only attempt, so it keeps the cookies the operator configured.
    # Every attempt asks for the same 1080p spec: the fallback used to ask
    # for `best[ext=mp4]/best`, the best single-file format, which on
    # YouTube is the 360p progressive one even with 1080p streams listed.
    attempts = [
        (label,
         fallback_args if label.startswith('fallback') else hd_args,
         _hd_fmt_for(capped),
         proxy,
         not (label.startswith('fallback') and hd_args))
        for label, capped, proxy in plan_download_attempts(
            _direct_first, _statics, _proxy, bool(hd_args), youtube=is_youtube_url(url))
    ]
    if not is_youtube_url(url):
        print("🌐 Direct file URL: downloading from the server's own IP (no proxy).")

    sanitized_title = None
    last_err = None
    used_proxy = False
    # Every attempt, with its bytes and failure text: printed as PROXY_ROUTE=
    # below so app.py can keep a durable trail of WHY a job reached the paid
    # proxy (the container log rotates within the hour; see cloud/proxy_ledger).
    attempt_log = []
    for label, ea, fmt, proxy, cookies in attempts:
        # A 403 on the media fetch is usually transient: the googlevideo URL is
        # bound to the IP that extracted it, and the residential proxy rotates
        # its exit IP between requests. Retrying re-extracts and usually lands
        # on a consistent IP (3 of 62 downloads hit this on 22-jul-2026).
        for retry in range(2):
            try:
                print(f"📥 Download attempt: {label}" + (f" (retry {retry})" if retry else ""))
                sanitized_title = _attempt(ea, fmt, proxy, cookies)
                # Only bytes through the PER-GB proxy cost money; direct and
                # the flat-rate static proxies are free bandwidth for the
                # monthly counter's purposes.
                used_proxy = proxy is not None and proxy == _proxy
                attempt_log.append({"label": label, "ok": True,
                                    "bytes": _dl_bytes["total"] + _dl_bytes["partial"],
                                    "paid": used_proxy})
                print(f"✅ Download succeeded ({label}).")
                break
            except Exception as e:
                last_err = e
                attempt_log.append({"label": label, "ok": False,
                                    "bytes": _dl_bytes["total"] + _dl_bytes["partial"],
                                    "paid": proxy is not None and proxy == _proxy,
                                    "error": str(e)[:300]})
                print(f"⚠️  Download attempt '{label}' failed: {str(e)[:200]}")
                retryable = '403' in str(e) or 'Forbidden' in str(e)
                if not retryable or retry == 1:
                    break
                time.sleep(3)
        if sanitized_title is not None:
            break

    if sanitized_title is None:
        import sys
        error_msg = f"""
❌ ================================================================= ❌
❌ FATAL ERROR: YOUTUBE DOWNLOAD FAILED (all strategies)
❌ ================================================================= ❌
REASON: YouTube blocked the request or the download tooling is out of date.
👇 SOLUTION FOR USER: download the video manually and use the 'Upload Video' tab.
Technical Details: {str(last_err)}
"""
        print(error_msg, file=sys.stdout)
        print(error_msg, file=sys.stderr)
        sys.stdout.flush(); sys.stderr.flush()
        time.sleep(0.5)
        raise last_err

    downloaded_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    if not os.path.exists(downloaded_file):
        for f in os.listdir(output_dir):
            if f.startswith(sanitized_title) and f.endswith('.mp4'):
                downloaded_file = os.path.join(output_dir, f)
                break

    # Paid bytes across EVERY attempt that used the per-GB proxy, failed ones
    # included: a paid attempt that died after three 10 MB fragments was
    # billed for them even though a later attempt won.
    paid_bytes = sum(int(a.get("bytes") or 0) for a in attempt_log if a.get("paid"))
    print("PROXY_ROUTE=" + json.dumps({
        "winner": attempt_log[-1]["label"] if attempt_log and attempt_log[-1].get("ok") else None,
        "paid_bytes": paid_bytes,
        "attempts": attempt_log,
    }, ensure_ascii=False))
    if paid_bytes:
        # Machine-parseable marker consumed by app.py's log reader for the
        # monthly proxy-bandwidth counter. Not shown to clients (log filter).
        print(f"PROXY_BYTES={paid_bytes}")
    print(f"✅ Video downloaded in {time.time() - step_start_time:.2f}s: {downloaded_file}")
    return downloaded_file, sanitized_title

def finalize_clip_passthrough(input_video, final_output_video):
    """Keep the clip's native framing (for horizontal/16:9 output).

    The input is the freshly encoded cut, so a stream-copy remux is enough to
    add +faststart — re-encoding here would only cost time and quality.
    """
    if os.path.exists(final_output_video):
        os.remove(final_output_video)
    print(f"🎬 Passthrough (native framing): {input_video}")
    cmd = [
        'ffmpeg', '-y', '-i', input_video,
        '-c', 'copy', *METADATA_SCRUB, '-movflags', '+faststart',
        final_output_video,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    print(f"✅ Clip saved to {final_output_video}")
    return True


def auto_caption_clip(clip_path, transcript, clip_start, clip_end,
                      split_ranges=None, editorial_ranges=None, blur_ranges=None):
    """Burn the default caption style onto a finished clip.

    ``split_ranges``: (start, end) stretches, in clip seconds, rendered with
    the SPLIT layout; captions there sit on the seam between the two speakers
    instead of the bottom. None reads the render's own sidecar next to
    ``clip_path`` (layout_ranges), which is where recut hands it over.

    Captions are mandatory for short-form to land, but they were opt-in behind a
    modal and only 9% of delivered clips ever got them (prod audit, 25-jul-2026).
    So every clip now ships captioned by default.

    The captioned file is written ALONGSIDE the clip as
    ``subtitled_<ts>_<clip>.mp4`` — the same convention /api/subtitle uses — so
    the untouched original stays on disk and re-styling from the modal replaces
    the captions instead of burning a second layer over them.

    Returns the captioned path, or None when captions were skipped (silent
    video, no words in range, AUTO_CAPTIONS=0, or any failure — a caption
    problem must never cost the user the clip they already paid for).
    """
    if os.environ.get("AUTO_CAPTIONS", "1").strip() == "0":
        return None
    if not transcript or not transcript.get('segments'):
        return None  # silent video: nothing to caption
    try:
        import subtitles as _subs
        style = _subs.AUTO_CAPTION_STYLE
        output_dir = os.path.dirname(clip_path)
        stem = os.path.basename(clip_path)
        generation_id = int(time.time())
        # The output name MUST stay exactly "subtitled_<ts>_<clip filename>":
        # the modal's walk-back and _canonical_clip_file both reconstruct the
        # clean original from it, so trimming the stem here would orphan the
        # pair. Length is bounded upstream instead, by MAX_TITLE_BYTES at
        # download time. A legacy clip whose name predates that budget can still
        # overflow — that raises OSError 36, which the except below turns into
        # "ship the clip uncaptioned" rather than a broken filename.
        # The .ass path is interpolated INTO an ffmpeg filter string
        # (-vf ass='...'), where a literal apostrophe closes the quote and
        # breaks the filter. Titles carry apostrophes constantly in English
        # ("Earth's", "Don't"), so this name must stay free of the clip stem —
        # which is exactly why /api/subtitle has always used a neutral
        # "subs_<i>_<ts>.ass". Deriving it from the stem silently cost captions
        # on every apostrophe title until 29-jul-2026.
        #
        # The OUTPUT name still carries the stem, and must: the modal's
        # walk-back and _canonical_clip_file reconstruct the clean original
        # from it. That one is only ever passed as an argv element, never
        # inside a filter string, so quoting never applies to it.
        # Unique per clip, not just per second: clips render in parallel
        # (CLIP_WORKERS), so a bare timestamp would collide and let one clip
        # burn another's captions.
        ass_path = os.path.join(
            output_dir, f"autosubs_{generation_id}_{uuid.uuid4().hex[:8]}.ass")
        out_path = os.path.join(output_dir, f"subtitled_{generation_id}_{stem}")

        if split_ranges is None or editorial_ranges is None:
            import layout_ranges as _layouts
            recorded = _layouts.read(clip_path)
            if split_ranges is None:
                split_ranges = _layouts.split_ranges(recorded)
            if editorial_ranges is None:
                editorial_ranges = _layouts.editorial_ranges(recorded)
        import caption_renderer
        if blur_ranges is None:
            import layout_ranges as _layouts
            blur_ranges=_layouts.blur_ranges(_layouts.read(clip_path))
        preset=os.getenv('CAPTION_PRESET','classic')
        if preset=='classic' and blur_ranges:
            preset='bold-creator'
        if preset in caption_renderer.PRESETS:
            width,height=get_video_resolution(clip_path)
            generated=caption_renderer.generate(transcript,clip_start,clip_end,ass_path,
                width or 1080,height or 1920,preset,splits=split_ranges,editorials=editorial_ranges,
                blurs=blur_ranges,
                faces=caption_renderer.detect_face_regions(clip_path,clip_end-clip_start))
        elif preset == "clean":
            import clean_captions
            width, height = get_video_resolution(clip_path)
            generated = clean_captions.generate(transcript, clip_start, clip_end, ass_path,
                                                 width or 1080, height or 1920,
                                                 split_ranges, editorial_ranges)
        else:
            generated = _subs.generate_ass(
                transcript, clip_start, clip_end, ass_path,
                split_ranges=split_ranges,
                max_chars=style["max_chars"], max_duration=style["max_duration"],
                alignment=style["alignment"], fontsize=style["font_size"],
                font_name=style["font_name"], font_color=style["font_color"],
                border_color=style["border_color"], border_width=style["border_width"],
                highlight_color=style["highlight_color"], effect=style["effect"],
                base_opacity=style["base_opacity"], uppercase=style["uppercase"])
        if not generated:
            print("   ℹ️ No words in range — clip ships without captions.")
            return None

        _subs.burn_subtitles(
            clip_path, ass_path, out_path,
            alignment=style["alignment"], fontsize=style["font_size"],
            font_name=style["font_name"], font_color=style["font_color"],
            border_color=style["border_color"], border_width=style["border_width"])
        print(f"   💬 Captions burned: {os.path.basename(out_path)}")
        return out_path
    except Exception as e:
        print(f"   ⚠️ Auto-captions failed ({type(e).__name__}: {e}) — "
              f"delivering the clip without them.")
        return None


def auto_hook_clip(clip_path, clip, transcript=None, start=0., end=None):
    """Burn the clip's Gemini hook text as a DERIVED file (AUTO_HOOK=1).

    Writes ``hooked_<ts>_<clip filename>`` next to the canonical clip, exactly
    like captions write ``subtitled_<ts>_...``: the canonical stays clean, so
    the hook can later be replaced or removed by walking the prefix back
    (app.py `_strip_burned_hook`). Captions are then burned ON TOP of the
    hooked file, keeping the "captions are always the last layer" invariant.

    Returns (hooked_path, hook_config), or None when skipped or failed — a
    hook problem must never cost the user the clip itself (same fail-open
    contract as auto_caption_clip)."""
    import hook_layer
    try:
        duration=float(end-start) if end is not None else float(clip.get('end',0)-clip.get('start',0))
        decision=hook_layer.suggest(hook_layer.source_rows(transcript,[dict(start=start,end=start+duration)]),duration,
            hint=clip.get('viral_hook_text') or '',context_kind=clip.get('editing_strategy','general'),
            scenes=[r['start'] for r in clip.get('layout_ranges',[])]) if duration>0 else None
    except (ValueError,TypeError,KeyError):return None
    if not decision:
        return None
    text=decision['text']
    style = os.environ.get("AUTO_HOOK_STYLE", "classic")
    try:
        seconds = min(3.,duration,float(os.environ.get("AUTO_HOOK_SECONDS", "3")))
    except ValueError:
        seconds = min(3.,duration)
    try:
        from hooks import add_hook_to_video, HOOK_STYLES
        if style not in HOOK_STYLES:
            style = "classic"
        import caption_renderer
        faces=caption_renderer.detect_face_regions(clip_path,duration)+hook_layer.context_regions(clip.get('layout_ranges',[]))
        if hook_layer.placement(dict(text=text,end=seconds),faces) is None:return None
        output_dir = os.path.dirname(clip_path)
        out_path = os.path.join(
            output_dir, f"hooked_{int(time.time())}_{os.path.basename(clip_path)}")
        add_hook_to_video(clip_path, text, out_path, position="top",
                          duration=seconds, style=style,animation='fade',faces=faces)
        print(f"   🪝 Hook burned ({style}, {seconds:g}s): {text}")
        return out_path, {"text": text, "style": style, "position": "top",
                          "duration_seconds": seconds,"start_seconds":0.,"animation":"fade","grounding":decision}
    except Exception as e:
        print(f"   ⚠️ Auto-hook failed ({type(e).__name__}: {e}) — "
              f"delivering the clip without it.")
        return None


def render_clip(input_video, final_output_video, output_format="auto",
                force_strategy=None, crop_overrides=None, director_context=None):
    """Route a cut clip through the right renderer for the chosen output format.
    vertical/auto -> 9:16 reframe, square -> 1:1 reframe, horizontal -> keep.
    ``force_strategy`` (e.g. 'WIDE'/'TRACK') pins every scene's layout — the
    clip editor's whole-clip framing override. ``crop_overrides`` positions
    individual scenes by hand (the per-scene reframing editor) and wins over
    ``force_strategy`` for the scenes it names."""
    if output_format == "horizontal":
        return finalize_clip_passthrough(input_video, final_output_video)
    aspect = 1.0 if output_format == "square" else ASPECT_RATIO
    import editing_director
    if editing_director.enabled():
        import reframe_v2
        return reframe_v2.render(input_video,final_output_video,aspect,
            force_strategy=force_strategy,crop_overrides=crop_overrides,director_context=director_context)
    return process_video_to_vertical(input_video, final_output_video, aspect_ratio=aspect,
                                     force_strategy=force_strategy,
                                     crop_overrides=crop_overrides)


# Watermark geometry, as fractions of the clip width/height.
#
# Vertical placement is the whole point: the top and bottom strips of a 9:16
# clip are either black bars or blurred filler (GENERAL layout), so a mark up
# there is cropped away without touching a single pixel of real footage. At 40%
# of the height it sits inside the content band — a 16:9 source letterboxed
# into 9:16 spans roughly 34%-66% — so removing the mark means cutting into the
# picture. Left-aligned, like OpusClip's.
WATERMARK_WIDTH_RATIO = 0.30
WATERMARK_MARGIN_RATIO = 0.05
WATERMARK_Y_RATIO = 0.40
WATERMARK_OPACITY = 0.85


def apply_watermark(video_path, runner=None):
    """Burn the OpenShorts watermark into a finished clip (free plan).

    One re-encode pass on the final file so every output format (TRACK,
    GENERAL, horizontal passthrough) gets the mark, and later subtitle/hook
    re-encodes keep it — they re-encode the already-marked pixels.
    """
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "watermark.png")
    if not os.path.exists(logo_path):
        print(f"   ⚠️ Watermark asset missing ({logo_path}); clip kept unmarked.")
        return False

    # Scale the lockup from the clip's real width: overlay can't read the other
    # input's size, and computing it here avoids the deprecated scale2ref.
    try:
        probe = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video_path],
            stderr=subprocess.STDOUT, timeout=60,
        ).decode().strip().split("x")
        vw, vh = int(probe[0]), int(probe[1])
    except Exception as e:
        print(f"   ⚠️ Could not probe clip for watermark ({e}); clip kept unmarked.")
        return False

    wm_w = max(80, int(vw * WATERMARK_WIDTH_RATIO))
    x = int(vw * WATERMARK_MARGIN_RATIO)
    y = int(vh * WATERMARK_Y_RATIO)
    filt = (
        f"[1:v]scale={wm_w}:-1,format=rgba,"
        f"colorchannelmixer=aa={WATERMARK_OPACITY}[wm];"
        f"[0:v][wm]overlay=x={x}:y={y}"
    )
    tmp_path = video_path + ".wm.mp4"
    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", logo_path,
           "-filter_complex", filt,
           *video_encode_args(QUALITY), "-c:a", "copy", *METADATA_SCRUB,
           "-movflags", "+faststart", tmp_path]
    if runner is not None:
        runner(cmd)
        result = subprocess.CompletedProcess(cmd, 0)
    else:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=1800)
    if result.returncode == 0 and os.path.exists(tmp_path):
        os.replace(tmp_path, video_path)
        return True
    err = (result.stderr or b"").decode(errors="ignore")[-300:]
    print(f"   ⚠️ Watermark pass failed (clip kept unmarked): {err}")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    return False


def process_video_to_vertical(input_video, final_output_video, aspect_ratio=ASPECT_RATIO,
                              force_strategy=None, crop_overrides=None):
    """
    Core logic to reframe a horizontal video to a target aspect ratio using
    scene detection and Active Speaker Tracking (MediaPipe).
    aspect_ratio: width/height of the output (9/16 vertical, 1.0 square).
    force_strategy / crop_overrides pin layouts and scene crops by hand (v2
    engine only — the v1 loop below has no layout concept beyond its own
    classifier).
    """
    # v2 engine: analyze downscaled, render natively in ffmpeg. Any failure
    # falls back to the v1 frame loop below so a v2 edge case can't kill jobs.
    if os.environ.get("REFRAME_ENGINE", "v2").strip().lower() != "v1":
        try:
            import reframe_v2
            t0 = time.time()
            result = reframe_v2.render(input_video, final_output_video, aspect_ratio,
                                       force_strategy=force_strategy,
                                       crop_overrides=crop_overrides)
            print(f"   ⏱️ Reframe v2 total: {time.time() - t0:.1f}s")
            return result
        except Exception as e:
            # Only v2 honours hand-framed scenes and forced layouts. Falling
            # through to v1 would quietly return an automatically framed clip,
            # and the user would see their correction vanish with no reason
            # given — so surface the failure instead of discarding their input.
            if crop_overrides or force_strategy:
                raise RuntimeError(
                    f"manual framing needs the v2 reframe engine, which failed "
                    f"({type(e).__name__}: {e})") from e
            print(f"   ⚠️ Reframe v2 failed ({type(e).__name__}: {e}) — "
                  f"falling back to v1 frame loop")

    # The v1 loop stages its work next to the final file: a silent video track
    # first, then the source audio, muxed together at the end.
    stem = os.path.splitext(final_output_video)[0]
    silent_video_path = stem + ".v1video.mp4"
    audio_track_path = stem + ".v1audio.aac"
    for stale in (silent_video_path, audio_track_path, final_output_video,str(final_output_video)+'.framing.json'):
        # isfile, not exists: a caller that hands us a directory should not
        # take an EACCES here, and must never have it deleted either.
        if os.path.isfile(stale):
            os.remove(stale)

    print(f"🎬 Processing clip: {input_video}")
    print("   Step 1: Detecting scenes...")
    scenes, fps = detect_scenes(input_video)
    
    if not scenes:
        # Scene detection found nothing: treat the whole video as one scene.
        print("   ❌ No scenes were detected. Using full video as one scene.")
        probe = cv2.VideoCapture(input_video)
        span = int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
        probe.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(span, fps))]

    print(f"   ✅ Found {len(scenes)} scenes.")

    print("\n   🧠 Step 2: Preparing Active Tracking...")
    original_width, original_height = get_video_resolution(input_video)
    
    # Same delivery floor as the v2 engine — a fallback render is still the clip
    # the user posts, so it must not ship sub-HD. The frame loop below already
    # resizes every cropped frame to these dims, so nothing else changes.
    from reframe_v2 import delivery_size
    OUTPUT_WIDTH, OUTPUT_HEIGHT = delivery_size(original_width, original_height,
                                                aspect_ratio)

    # Initialize Cameraman
    cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT, original_width, original_height, aspect_ratio=aspect_ratio,fps=float(fps))
    
    # --- New Strategy: Per-Scene Analysis ---
    print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
    scene_strategies = analyze_scenes_strategy(input_video, scenes, aspect_ratio)
    # scene_strategies is a list of 'TRACK' or 'General' corresponding to scenes
    
    print("\n   ✂️ Step 4: Processing video frames...")
    
    # Raw BGR frames stream down a pipe into ffmpeg, which encodes the silent
    # video track; the audio is muxed back in afterwards.
    # The legacy raw-frame pipe cannot replay consumed stdin after NVENC dies.
    # Use the stable CPU encoder here; v2 file/filter rendering supports NVENC.
    from ffmpeg_utils import cpu_encoding
    with cpu_encoding():frame_encoder_args=video_encode_args(QUALITY_FAST)
    encoder = subprocess.Popen(
        ['ffmpeg', '-y','-v','error','-nostats',
         '-f', 'rawvideo', '-pix_fmt', 'bgr24',
         '-video_size', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}',
         '-framerate', str(fps), '-i', 'pipe:0',
         *frame_encoder_args, '-threads',str(__import__('render_runtime').limits()['threads']),
         '-pix_fmt','yuv420p','-an', silent_video_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    reader = cv2.VideoCapture(input_video)
    frame_total = int(reader.get(cv2.CAP_PROP_FRAME_COUNT))
    
    frame_number = 0
    current_scene_index = 0
    
    # Pre-calculate scene boundaries
    scene_boundaries = []
    for s_start, s_end in scenes:
        scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

    # Global tracker for single-person shots
    speaker_tracker = SpeakerTracker(cooldown_frames=max(1,round(float(fps))),fps=float(fps))

    # Per-stage wall time (server-side diagnostics; hidden from cloud logs).
    stage_seconds = {'detect': 0.0, 'write': 0.0}
    loop_started = time.time()

    with tqdm(total=frame_total, desc="   Processing", file=sys.stdout) as pbar:
        while reader.isOpened():
            ret, frame = reader.read()
            if not ret:
                break

            resolution_changed = frame.shape[1] != original_width or frame.shape[0] != original_height
            aspect_changed = False
            if resolution_changed:
                # Some camera recordings switch resolution mid-stream. The v2
                # renderer may reject a fixed crop and land here; never reuse
                # pixel coordinates belonging to the previous raster.
                new_h, new_w = frame.shape[:2]
                aspect_changed = abs(new_w/new_h - original_width/original_height) > .01
                original_width, original_height = new_w, new_h
                cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT,
                    original_width, original_height, aspect_ratio=aspect_ratio,fps=float(fps))
                speaker_tracker.reset()
                cameraman.begin_scene()

            # Update Scene Index
            if current_scene_index < len(scene_boundaries):
                start_f, end_f = scene_boundaries[current_scene_index]
                if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                    current_scene_index += 1
            
            # Determine Strategy for current frame based on scene
            current_strategy = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
            if aspect_changed:
                # The camera was rebuilt for this raster above. A portrait shot
                # can safely use that fresh crop; forcing GENERAL exposed dimmed
                # background bars (120 -> 104) after a landscape/portrait switch.
                scene_strategies[current_scene_index] = current_strategy = (
                    'GENERAL' if original_width / original_height >= 1.3 else 'TRACK')
            
            # Apply Strategy
            if current_strategy == 'GENERAL':
                # Landscape groups keep the full context in a lower panel
                # while the upper panel fills the screen with readable detail.
                if (__import__('video_templates').framing_preference() == 'editorial'
                        and aspect_ratio < .7
                        and original_width / original_height >= 1.3):
                    output_frame = create_editorial_frame(
                        frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                else:
                    output_frame = create_general_frame(
                        frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                
                # Reset cameraman/tracker so they don't drift while inactive
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2
                
            else:
                # "Single Speaker" -> Track & Crop

                # Detect every Nth frame for performance (cameraman smooths in
                # between); the much heavier YOLO fallback gets its own stride.
                # Snap camera on scene change to avoid panning from previous scene position
                is_scene_start = resolution_changed or (frame_number == scene_boundaries[current_scene_index][0])
                if is_scene_start and SCENE_CUT_RESET:
                    speaker_tracker.reset()
                    cameraman.begin_scene()

                # Always detect on a cut, whatever the stride: the new shot's
                # subject has to be found before the first frame is framed.
                if frame_number % DETECT_STRIDE == 0 or (is_scene_start and SCENE_CUT_RESET):
                    t_det = time.time()
                    candidates = detect_face_candidates(frame)
                    target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                    if target_box:
                        cameraman.update_target(target_box)
                    elif not candidates and (frame_number % YOLO_FALLBACK_STRIDE == 0 or (is_scene_start and SCENE_CUT_RESET)):
                        person_box = detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target(person_box)
                    stage_seconds['detect'] += time.time() - t_det

                x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)

                # Crop
                if y2 > y1 and x2 > x1:
                    cropped = frame[y1:y2, x1:x2]
                    output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_LINEAR)
                else:
                    output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT), interpolation=cv2.INTER_LINEAR)

            t_wr = time.time()
            encoder.stdin.write(output_frame.tobytes())
            stage_seconds['write'] += time.time() - t_wr
            frame_number += 1
            pbar.update(1)
    
    loop_total = time.time() - loop_started
    other = loop_total - stage_seconds['detect'] - stage_seconds['write']
    print(f"\n   ⏱️ Frame loop: {loop_total:.1f}s total — "
          f"detect {stage_seconds['detect']:.1f}s, "
          f"encode-wait {stage_seconds['write']:.1f}s, "
          f"decode+render {other:.1f}s ({frame_number} frames)")

    encoder.stdin.close()
    encode_log = encoder.stderr.read().decode()
    encoder.wait()
    reader.release()

    if encoder.returncode != 0:
        print("\n   ❌ FFmpeg frame processing failed.")
        print("   Stderr:", encode_log)
        return False

    print("\n   🔊 Step 5: Extracting audio...")
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', input_video, '-vn', '-c:a', 'copy', audio_track_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print("\n   ❌ Audio extraction failed (maybe no audio?). Proceeding without audio.")

    print("\n   ✨ Step 6: Merging...")
    mux = ['ffmpeg', '-y', '-i', silent_video_path]
    if os.path.exists(audio_track_path):
        mux += ['-i', audio_track_path]
    mux += ['-c', 'copy', *METADATA_SCRUB, '-movflags', '+faststart', final_output_video]
    try:
        subprocess.run(mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"   ✅ Clip saved to {final_output_video}")
    except subprocess.CalledProcessError as e:
        print("\n   ❌ Final merge failed.")
        print("   Stderr:", e.stderr.decode())
        return False

    for leftover in (silent_video_path, audio_track_path):
        if os.path.exists(leftover):
            os.remove(leftover)

    return True

# --- Transcript checkpoint (survive a redeploy without paying twice) ---------
# A job interrupted by a container restart is re-run from its resume manifest
# (app.py) with the SAME output directory. Transcription is the slow, paid part
# of the pipeline that ran before the interruption, so the finished transcript
# is left in the job directory and picked up by the re-run instead of
# transcribing again. Same shape and same validation as --transcript.
TRANSCRIPT_CHECKPOINT = ".transcript_checkpoint.json"


def _checkpoint_source_key(input_video, duration):
    """What ties a checkpoint to ONE source. Not the path: a resumed cloud job
    re-downloads to the same name, and the CLI may be pointed at a different
    file in a directory where an earlier run died. Name plus duration is what
    both the server and a careful CLI user keep stable across the two runs."""
    return {"name": os.path.basename(input_video), "duration": round(float(duration), 1)}


def save_transcript_checkpoint(output_dir, transcript, input_video, duration):
    """Best effort: a failure here must never fail the job."""
    try:
        payload = {"source": _checkpoint_source_key(input_video, duration),
                   "transcript": transcript}
        with open(os.path.join(output_dir, TRANSCRIPT_CHECKPOINT), "w") as f:
            json.dump(payload, f)
    except Exception as e:
        print(f"⚠️ Could not save transcript checkpoint: {e}")


def load_transcript_checkpoint(output_dir, input_video, duration):
    """The transcript an interrupted run left behind for THIS source, or None.

    A checkpoint for a different source (a CLI run that died, then a new video
    processed in the same directory) is ignored, not reused."""
    path = os.path.join(output_dir, TRANSCRIPT_CHECKPOINT)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        source = payload.get("source") or {}
        expected = _checkpoint_source_key(input_video, duration)
        if source.get("name") != expected["name"] \
                or abs(float(source.get("duration", -1)) - expected["duration"]) > 0.5:
            print("⏭️ Transcript checkpoint belongs to another source — ignoring it.")
            return None
        transcript = payload.get("transcript") or {}
        if not transcript.get("segments"):
            raise ValueError("checkpoint has no segments")
        return transcript
    except Exception as e:
        print(f"⚠️ Ignoring unusable transcript checkpoint ({e}).")
        return None


def clear_transcript_checkpoint(output_dir):
    try:
        os.remove(os.path.join(output_dir, TRANSCRIPT_CHECKPOINT))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Could not remove transcript checkpoint: {e}")


def transcribe_video(video_path):
    print("🎙️  Transcribing video...")
    from transcribe_backends import transcribe_media

    transcript = transcribe_media(video_path)

    print(f"   Detected language '{transcript['language']}', "
          f"{len(transcript['segments'])} segments")
    for segment in transcript['segments']:
        # Print progress to keep user informed (and prevent timeouts feeling)
        print(f"   [{segment['start']:.2f}s -> {segment['end']:.2f}s] {segment['text']}")

    return transcript

def _gemini_api_keys():
    """Return configured Gemini keys in stable order, without duplicates.

    Supports a bounded pool of numbered GEMINI_API_KEY slots and
    remains backwards compatible with GEMINI_API_KEY.
    """
    return __import__('gemini_keys').configured()


def _gemini_clients():
    return [genai.Client(api_key=key,http_options=gemini_worker.http_options()) for key in _gemini_api_keys()]


def _gemini_is_key_retryable(exc):
    """Errors where trying the second configured key is useful/safe.

    Do not rotate on content-policy, invalid prompt/schema, or parsing errors.
    A project-level quota may be shared by both keys, but trying key #2 once is
    harmless and supports the case where the keys belong to different projects.
    """
    msg = str(exc).upper()
    return any(tok in msg for tok in (
        "429", "RESOURCE_EXHAUSTED", "RATE LIMIT", "QUOTA",
        "401", "403", "API_KEY", "API KEY", "PERMISSION_DENIED",
    ))


def _run_gemini_stage(client, model_name, prompt, schema):
    """Original schema-enforced Gemini call, with two-key support added.

    The original 2-pass/batched clip-selection logic is intentionally unchanged.
    503/service overload retries stay on the SAME key (5s, 10s). Key rotation is
    reserved for key/quota/auth errors so a temporary model-wide 503 does not
    waste requests across both keys.
    """
    use_local = llm_backend.active()
    config = None if use_local else genai_types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )
    max_attempts = 3
    request_prompt=prompt
    json_compat=False

    if use_local:
        clients = [None]
    else:
        clients = [client] if client is not None else _gemini_clients()
        if not clients:
            raise RuntimeError(
                "No Gemini API key configured. Set GEMINI_API_KEY_1 / "
                "GEMINI_API_KEY_2 (or GEMINI_API_KEY).")

    last_error = None
    for key_index, active_client in enumerate(clients):
        for attempt in range(1, max_attempts + 1):
            try:
                if use_local:
                    return llm_backend.generate_json(prompt, schema, model=model_name)

                response = active_client.models.generate_content(
                    model=model_name, contents=request_prompt, config=config)
                gemini_worker.raise_if_blocked(response)

                parsed_obj = getattr(response, "parsed", None)
                if parsed_obj is not None:
                    parsed = (parsed_obj.model_dump()
                              if hasattr(parsed_obj, "model_dump") else parsed_obj)
                else:
                    parsed = gemini_worker._parse_json_response_text(
                        gemini_worker._get_response_text(response))
                if hasattr(schema,'model_validate'):
                    parsed=schema.model_validate(parsed).model_dump()
                return parsed, gemini_worker._calculate_cost_analysis(
                    response, model_name)

            except gemini_worker.GeminiBlockedError:
                raise
            except Exception as e:
                last_error = e
                msg = str(e)
                if (not use_local and not json_compat and attempt<max_attempts and
                    getattr(e,'code',None)==400 and 'INVALID_ARGUMENT' in msg.upper() and hasattr(schema,'model_json_schema')):
                    json_compat=True
                    config=genai_types.GenerateContentConfig(response_mime_type='application/json')
                    request_prompt=prompt+'\nReturn one JSON object matching this schema; do not invent missing evidence:\n'+json.dumps(schema.model_json_schema())
                    print('   Gemini selection: structured request rejected; retrying JSON with strict local validation.',flush=True)
                    continue

                # Key-specific/auth/quota problem: don't burn 3 retries on this
                # key. Move to key #2 immediately when one exists.
                if (not use_local and _gemini_is_key_retryable(e)
                        and key_index + 1 < len(clients)):
                    print(f"⚠️ Gemini key #{key_index + 1} hit a key/quota error; "
                          f"trying key #{key_index + 2}: {msg[:150]}")
                    break

                transient = any(tok in msg for tok in (
                    '503', 'UNAVAILABLE', '429', 'RESOURCE_EXHAUSTED',
                    '500', 'INTERNAL', 'overloaded', 'Deadline',
                    'empty response body', 'did not contain a JSON object',
                    'Failed to parse Gemini JSON response',
                    'ConnectError', 'ReadTimeout', 'RemoteProtocolError',
                    '502', '504', 'validation error'))

                if attempt == max_attempts or not transient:
                    # If this was the final key, surface the real provider error.
                    raise

                wait = 5 * (2 ** (attempt - 1))
                who = "LLM server" if use_local else f"Gemini key #{key_index + 1}"
                print(f"⚠️ {who} transient error (attempt {attempt}/{max_attempts}), "
                      f"retrying in {wait}s: {msg[:150]}")
                time.sleep(wait)

        else:
            continue

        # Inner loop was broken to rotate key.
        continue

    if last_error:
        raise last_error
    raise RuntimeError("Gemini request failed without a provider error.")


def _run_stage_split(client, model_name, items, build_prompt, schema, key, costs, label):
    """Run a Gemini stage over ``items``; on a policy block, bisect.

    Google's prompt filter (PROHIBITED_CONTENT) fires on some COMBINATIONS of
    transcript windows that pass individually (27-aug-2026: windows 5+6 of a
    software walkthrough blocked 3/3, each alone fine, all three models).
    A block is deterministic for a given prompt, so instead of failing the
    job the batch is split in halves until the offending combination is
    isolated; a single item that still blocks is dropped with a log line.
    Returns the merged list found under ``key`` in each response."""
    if not items:
        return []
    prompt = build_prompt(items)
    try:
        parsed, cost = _run_gemini_stage(client, model_name, prompt, schema)
        if cost:
            costs.append(cost)
        return clip_selection.CandidateBatch(parsed.get(key) or [])
    except gemini_worker.GeminiBlockedError as e:
        if len(items) == 1:
            print(f"   🚫 {label}: Gemini blocked window {items[0].get('id')} on its own; skipping it ({e})")
            return clip_selection.CandidateBatch(blocked=[items[0].get('id')])
        mid = len(items) // 2
        print(f"   🚫 {label}: Gemini blocked a batch of {len(items)}; retrying as {mid} + {len(items) - mid}")
        left=_run_stage_split(client, model_name, items[:mid], build_prompt, schema, key, costs, label)
        right=_run_stage_split(client, model_name, items[mid:], build_prompt, schema, key, costs, label)
        return clip_selection.CandidateBatch(left+right,blocked=getattr(left,'blocked',set())|getattr(right,'blocked',set()))


def score_batch_size():
    """Transcript windows per scoring call: ``LLM_SCORE_BATCH`` if set, else
    8 for Gemini (1M context) and 3 for an OpenAI-compatible server."""
    raw = os.environ.get("LLM_SCORE_BATCH", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 3 if llm_backend.active() else 8


def get_viral_clips(transcript_result, video_duration, analysis=None, output_dir=None, source_identity=None):
    """Two-pass clip selection: score transcript windows, then detail the best.

    Windowing gives even coverage on long videos (a single call over the whole
    transcript clusters picks near the start), and the cheap scoring pass keeps
    the expensive detail reasoning focused on the shortlist. Cuts are snapped to
    word boundaries so clips don't start/end mid-word.
    """
    language = str(transcript_result.get('language') or 'unknown')
    min_secs,max_secs=clip_duration_bounds()
    try: target=float(os.getenv('CLIP_TARGET_SECONDS',''))
    except ValueError: target=None
    story_aware=os.getenv('CLIP_STORY_AWARE','1')!='0'
    if target is not None and not (math.isfinite(target) and min_secs<=target<=max_secs): target=None
    visual=(analysis or {}).get('moments',[])
    cache_path=os.path.join(output_dir,'clip_selection.json') if output_dir else None
    cache_key=None
    blocked_windows=set()
    windows=[]
    costs=[]
    try:
        from learning.highlight_ranking import signature as ranking_signature
        cache_key=clip_selection.selection_cache_key(transcript_result,video_duration,analysis,{
            'source':source_identity,
            'local_ranker':ranking_signature(),'ranking_category':os.getenv('AMCE_CATEGORY','general'),
            'story_mode':story_director.configured_story_mode(),
            'ranking_weights':clip_ranking.configured_weights(),
            'bounds':[min_secs,max_secs],'target':target,'story_aware':story_aware,'model':os.getenv('GEMINI_MODEL'),
            'local_model':llm_backend.model_name() if llm_backend.active() else None,
            'endpoint':llm_backend.base_url() if llm_backend.active() else None,
            'count':[os.getenv('CLIP_TARGET_MIN'),os.getenv('CLIP_TARGET_MAX')]})
        if cache_path:
            with open(cache_path,encoding='utf-8') as handle: cached=json.load(handle)
            if cached.get('key')==cache_key and cached.get('result',{}).get('shorts'):
                result=cached['result']
                if all(clip_selection.valid_range(c.get('start'),c.get('end'),video_duration) for c in result['shorts']):
                    return {**result,'selection_cache_hit':True,'cost_analysis':None}
    except (OSError,ValueError,TypeError,AttributeError): pass

    def finish(candidates, costs=None, fallback=False):
        _,limit=clip_count_targets(10)
        if fallback:
            candidates=clip_selection.fallback_story_candidates(transcript_result,video_duration,min_secs,max_secs,target)
        # Never reintroduce isolated provider-blocked windows via local fallback.
        excluded=[w for w in windows if w['id'] in blocked_windows]
        candidates=[c for c in candidates if not any(
            min(c.get('end',0),w['end'])>max(c.get('start',0),w['start']) for w in excluded)]
        if story_aware:
            chosen=clip_selection.select_story_candidates(candidates,transcript_result,video_duration,
                min_secs,max_secs,limit,visual,scene_cuts=(analysis or {}).get('scene_cuts',()),target=target,
                learning_context=dict(source_group=(source_identity or {}).get('sha256'),kind=os.getenv('AMCE_CATEGORY','general')))
        else:
            import recut
            words=recut.transcript_words(transcript_result)
            adjusted=[]
            for candidate in candidates:
                if not clip_selection.valid_range(candidate.get('start'),candidate.get('end'),video_duration): continue
                a,b=snap_clip_to_words(candidate['start'],candidate['end'],words,video_duration,min_secs,max_secs)
                adjusted.append({**candidate,'start':a,'end':b})
            chosen=trim_to_best(story_director.validate_moments(adjusted,video_duration,min_secs,max_secs),limit)
        if not chosen and not fallback: return finish([],costs,True)
        if not chosen: return None
        result={'shorts':chosen,'cost_analysis':costs,'selection_fallback':fallback}
        # Do not persist provider-outage fallback: a later retry can use AI again.
        if cache_path and cache_key and not fallback:
            try: story_director.atomic_json(cache_path,{'key':cache_key,'result':result})
            except OSError: pass
        return result
    if llm_backend.active():
        # Self-hosted text model: no Google key needed for this stage.
        client = None
        model_name = llm_backend.model_name()
        print(f"\U0001f916  Analyzing with local LLM at {llm_backend.base_url()} (2-pass: score → detail)...")
    else:
        print("\U0001f916  Analyzing with Gemini (2-pass: score → detail)...")
        api_keys = _gemini_api_keys()
        if not api_keys:
            print("⚠️ No Gemini key configured; selecting source speech locally.")
            return finish([],fallback=True)
        client = None
        if len(api_keys) > 1:
            print(f"🔑 Gemini API keys loaded: {len(api_keys)}")
        model_name = os.environ.get("GEMINI_MODEL") or 'gemini-3.1-flash-lite'
    print(f"\U0001f916  Model: {model_name} | language: {language}")

    try:
        # Scoring windows must be able to CONTAIN a max-length clip (the detail
        # prompt keeps clips inside their candidate window), so scale them with
        # the requested band — a user asking for 60-90s clips on the default
        # 90s windows would get clips squeezed against the window walls.
        min_secs, max_secs = clip_duration_bounds()
        windows = build_transcript_windows(
            transcript_result, video_duration,
            window_seconds=max(90, int(max_secs * 1.5)))
        print(f"   Built {len(windows)} scoring window(s).")

        # --- Pass 1: score windows in batches, keep the highest-scoring ---
        scored = []
        # Local models usually run with a 4-8k context (Ollama defaults to
        # 4096 unless OLLAMA_CONTEXT_LENGTH says otherwise) and 8 windows of
        # transcript do not fit; a silently truncated prompt scores garbage.
        SCORE_BATCH = score_batch_size()
        def _payload(ws):
            return [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"],
                     "timed_sentences": story_director.timed_segments(transcript_result, w["start"], w["end"]),
                     "visual_context": [m for m in visual if m['end']>w['start'] and m['start']<w['end']],
                     "source_context": {'opening':windows[0]['text'][:500], 'ending':windows[-1]['text'][-500:]}}
                    for w in ws]

        def _score_prompt(ws):
            return story_director.story_instructions(full=False)+gemini_worker.SCORE_PROMPT_TEMPLATE.format(
                video_duration=video_duration, language=language,
                windows_json=json.dumps(_payload(ws), ensure_ascii=False))

        for b in range(0, len(windows), SCORE_BATCH):
            batch=_run_stage_split(
                client, model_name, windows[b:b + SCORE_BATCH], _score_prompt,
                gemini_worker.ScoreResponse, "windows", costs, "score")
            blocked_windows.update(getattr(batch,'blocked',()))
            scored.extend(batch)

        # Shortlist the top windows; scale with duration so long videos surface
        # more candidates without exploding the detail call.
        scored.sort(key=lambda w: w.get("score", 0), reverse=True)
        target = max(3, min(10, int(video_duration // 90) + 2))
        by_id = {w["id"]: w for w in windows}
        shortlist=[]
        seen=set()
        for row in scored:
            ident=row.get('id')
            if ident in by_id and ident not in seen and ident not in blocked_windows:
                shortlist.append(by_id[ident]);seen.add(ident)
                if len(shortlist)>=target: break
        if not shortlist:
            available=[w for w in windows if w['id'] not in blocked_windows]
            count=min(target,len(available))
            shortlist=[available[round(i*(len(available)-1)/max(1,count-1))] for i in range(count)]
        print(f"   Shortlisted {len(shortlist)} window(s) for detail.")

        # --- Pass 2: detailed clip extraction on the shortlist ---
        min_clips, max_clips = clip_count_targets(len(shortlist))

        def _detail_prompt(ws):
            # A split batch keeps the full clip-count band: a short list can
            # still hold the best clips, and the model returns fewer anyway.
            return story_director.story_instructions()+gemini_worker.DETAIL_PROMPT_TEMPLATE.format(
                video_duration=video_duration, language=language,
                min_clips=min_clips, max_clips=max_clips,
                min_secs=min_secs, max_secs=max_secs,
                windows_json=json.dumps(_payload(ws), ensure_ascii=False))

        shorts = _run_stage_split(client, model_name, shortlist, _detail_prompt,
                                  gemini_worker.DetailResponse, "shorts", costs, "detail")
        blocked_windows.update(getattr(shorts,'blocked',()))
        allowed = {w['id']: w for w in shortlist}
        shorts = [s for s in shorts if s.get('source_window_id') in allowed
                  and clip_selection.valid_range(s.get('start'),s.get('end'),video_duration)
                  and allowed[s['source_window_id']]['start'] <= float(s.get('start', -1))
                  < float(s.get('end', -1)) <= allowed[s['source_window_id']]['end']]
        # Sentence-aware selection happens before ranking/trimming in finish().

        # Aggregate cost across both passes.
        cost_analysis = None
        if costs:
            cost_analysis = {
                "input_tokens": sum(c.get("input_tokens", 0) for c in costs),
                "output_tokens": sum(c.get("output_tokens", 0) for c in costs),
                "total_cost": sum(c.get("total_cost", 0) for c in costs),
                "model": model_name,
            }
            print(f"\U0001f4b0 Total cost ({model_name}, 2-pass, {len(costs)} calls): ${cost_analysis['total_cost']:.6f}")

        if not shorts:
            print("⚠️ 2-pass returned no clips.")
            return finish([],cost_analysis,True)

        return finish(shorts,cost_analysis)
    except gemini_worker.GeminiBlockedError as e:
        # Content-policy rejection: propagate so the job fails with the real
        # reason instead of a generic "no clips found".
        print(f"🚫 {e}")
        raise
    except Exception as e:
        print("⚠️ Clip analysis unavailable; selecting timed source extracts locally.")
        spent=({**{key:sum(c.get(key,0) for c in costs) for key in
                    ('total_cost','input_tokens','output_tokens')},'model':model_name}
               if costs else None)
        return finish([],spent,fallback=True)


# --- Speech too sparse to clip by transcript -------------------------------
# The vision path used to fire only on a missing audio TRACK. A nursery-rhyme
# video or a dashcam drive has audio, so it went through transcription, came
# back as one segment ("Uh uh"), produced one scoring window and Gemini
# returned no clips — three failed jobs on 25-aug-2026, one user twice. Speech
# is ~120-160 words/min; below these floors there is nothing to clip by words.
MIN_SPEECH_WORDS_PER_MIN = float(os.environ.get("MIN_SPEECH_WORDS_PER_MIN", "5"))
MIN_SPEECH_WORDS = int(os.environ.get("MIN_SPEECH_WORDS", "8"))


def speech_is_sparse(transcript, duration):
    """True when the transcript is too thin to drive clip selection."""
    words = sum(len((seg.get("text") or "").split())
                for seg in (transcript or {}).get("segments", []))
    minutes = max(float(duration or 0) / 60.0, 1e-6)
    return words < MIN_SPEECH_WORDS or words / minutes < MIN_SPEECH_WORDS_PER_MIN


def get_visual_clips(video_path, video_duration, language="en"):
    """Clip a SILENT video by vision: Gemini watches the footage and picks the
    most engaging visual moments (no transcript). Returns the same
    {"shorts", "cost_analysis"} shape as get_viral_clips, or None."""
    print("🎥  Silent video — analyzing with Gemini vision (no transcript)...")
    api_keys = _gemini_api_keys()
    api_key = api_keys[0] if api_keys else None
    if not api_key:
        if llm_backend.active():
            print("❌ This video has no usable speech, so it has to be clipped by "
                  "watching it, and that needs Gemini (a text-only LLM server "
                  "cannot see the footage). Add a GEMINI_API_KEY for silent videos.")
        else:
            print("❌ Error: GEMINI_API_KEY not found.")
        return None
    client = genai.Client(api_key=api_key,http_options=gemini_worker.http_options())
    model_name = os.environ.get("GEMINI_MODEL") or 'gemini-3.1-flash-lite'
    print(f"🎥  Model: {model_name} | uploading {os.path.basename(video_path)}…")

    file_upload = None
    try:
        file_upload = client.files.upload(file=video_path)
        deadline = time.time() + 180
        while True:
            info = client.files.get(name=file_upload.name)
            state = str(getattr(getattr(info, "state", info), "name", "")).upper()
            if state == "ACTIVE":
                break
            if state == "FAILED":
                print("❌ Gemini could not process the video.")
                return None
            if time.time() > deadline:
                print("❌ Gemini video processing timed out.")
                return None
            time.sleep(2)

        # The vision path has no scoring windows to derive a count from, so the
        # env targets (user request) apply directly over the classic 3-15.
        def _env_int(name, default):
            try:
                return max(1, int(os.environ.get(name, "")))
            except ValueError:
                return default
        v_min_clips = _env_int("CLIP_TARGET_MIN", 3)
        v_max_clips = max(v_min_clips, _env_int("CLIP_TARGET_MAX", 15))
        v_min_secs, v_max_secs = clip_duration_bounds()
        prompt = story_director.story_instructions()+gemini_worker.VISUAL_PROMPT_TEMPLATE.format(
            video_duration=video_duration, language=language,
            min_clips=v_min_clips, max_clips=v_max_clips,
            min_secs=v_min_secs, max_secs=v_max_secs)
        config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gemini_worker.VisualResponse,
        )
        response = client.models.generate_content(
            model=model_name, contents=[file_upload, prompt], config=config)
        gemini_worker.raise_if_blocked(response)
        parsed = gemini_worker.VisualResponse.model_validate(json.loads(response.text)).model_dump()
        shorts = parsed.get("shorts") or []
        # Reject invalid timestamps rather than turning them into invented cuts.
        clean = []
        for s in shorts:
            if (clip_selection.valid_range(s.get('start'),s.get('end'),video_duration)
                    and min(v_min_secs,video_duration)<=s['end']-s['start']<=v_max_secs):
                clean.append(s)
        for clip in clean:
            if clip.get('story'):
                clip['story']=story_director.grounded_story(clip,[],watched=True)
                clip['visual_evidence']='; '.join(e['description'] for e in clip['story']['evidence'] if e['channel']=='visual')
        if os.getenv('CLIP_STORY_AWARE','1')!='0':
            clean=clip_selection.select_story_candidates(clean,None,video_duration,min(v_min_secs,video_duration),v_max_secs,
                limit=v_max_clips,visual_moments=clean)
        if not clean:
            print("⚠️ Vision pass returned no usable clips.")
            return None

        cost = gemini_worker._calculate_cost_analysis(response, model_name)
        if cost:
            print(f"💰 Vision cost ({model_name}): ${cost.get('total_cost', 0):.6f}")
        result = {"shorts": clean}
        if cost:
            result["cost_analysis"] = cost
        return result
    except gemini_worker.GeminiBlockedError as e:
        print(f"🚫 {e}")
        raise
    except Exception as e:
        print(f"❌ Gemini vision error: {e}")
        return None
    finally:
        if file_upload is not None:
            try:
                client.files.delete(name=file_upload.name)
            except Exception:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AutoCrop-Vertical with Viral Clip Detection.")
    
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('-i', '--input', type=str, help="Path to the input video file.")
    input_group.add_argument('-u', '--url', type=str, help="YouTube URL to download and process.")
    
    parser.add_argument('-o', '--output', type=str, help="Output directory or file (if processing whole video).")
    parser.add_argument('--keep-original', action='store_true', help="Keep the downloaded YouTube video.")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert the whole video.")
    parser.add_argument('--format', type=str, default="auto", choices=["auto", "vertical", "horizontal", "square"],
                        help="Output aspect: vertical/auto (9:16), horizontal (keep 16:9), square (1:1).")
    parser.add_argument('--transcript', type=str,
                        help="Path to a precomputed transcript JSON (transcribe_media shape); skips transcription.")
    parser.add_argument('--story-mode',choices=['auto',*story_director.STORY_MODES],default=None,
                        help='Story selection policy; auto uses available source context.')
    parser.add_argument('--pacing-mode',choices=list(pacing.MODES),default=None)
    parser.add_argument('--trim-silence',action=argparse.BooleanOptionalAction,default=None)

    args = parser.parse_args()
    if args.story_mode:os.environ['STORY_MODE']=args.story_mode
    if args.pacing_mode:os.environ['PACING_MODE']=args.pacing_mode
    if args.trim_silence is not None:os.environ['PACING_TRIM_SILENCE']='1' if args.trim_silence else '0'
    output_format = args.format

    script_start_time = time.time()
    
    def _ensure_dir(path: str) -> str:
        """Create directory if missing and return the same path."""
        if path:
            os.makedirs(path, exist_ok=True)
        return path
    
    # 1. Get Input Video
    if args.url:
        # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
        # For whole-video runs (--skip-analysis), --output can be a file path.
        if args.output and not args.skip_analysis:
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default "."
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or "."
            else:
                output_dir = "."
        
        input_video, video_title = download_youtube_video(args.url, output_dir)
    else:
        input_video = args.input
        video_title = os.path.splitext(os.path.basename(input_video))[0]
        
        if args.output and not args.skip_analysis:
            # For multi-clip runs, treat --output as an OUTPUT DIRECTORY (create it if needed).
            output_dir = _ensure_dir(args.output)
        else:
            # If output is a directory, use it; if it's a filename, use its directory; else default to input dir.
            if args.output and os.path.isdir(args.output):
                output_dir = args.output
            elif args.output and not os.path.isdir(args.output):
                output_dir = os.path.dirname(args.output) or os.path.dirname(input_video)
            else:
                output_dir = os.path.dirname(input_video)

    if not os.path.exists(input_video):
        print(f"❌ Input file not found: {input_video}")
        exit(1)

    # Quota-wall offer: only the first N minutes were paid for (see
    # cap_source_duration). Must run before anything reads the file.
    if os.environ.get("MAX_SOURCE_MINUTES", "").strip():
        input_video = cap_source_duration(input_video, os.environ["MAX_SOURCE_MINUTES"])

    # Layout choice is per SOURCE video, not per clip: one upload and one call
    # instead of one per clip, and the answer is a property of the material
    # ("this is a screencast"), which does not change between its own clips.
    # It runs before any render so the modules are switched on in time.
    if layout_picker.ENABLED:
        try:
            _cap = cv2.VideoCapture(input_video)
            _fps = _cap.get(cv2.CAP_PROP_FPS) or 30.0
            _duration = int(_cap.get(cv2.CAP_PROP_FRAME_COUNT)) / _fps
            _w = int(_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            _h = int(_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            _cap.release()
            from reframe_v2 import source_already_fits  # imports main back
            # A source already shot vertical has no width to reorganise, and
            # the render passes it through whatever the model says. Asking
            # anyway costs a Gemini call per upload to be ignored.
            if _w and _h and source_already_fits(_w, _h, ASPECT_RATIO):
                print(f"   ↕️  Source is {_w}x{_h} — already vertical, no layout to pick.")
            else:
                layout_picker.pick_and_apply(input_video, _duration)
        except Exception as e:
            print(f"⚠️ Layout choice skipped ({e}) — using the default layout.")

    # 2. Decision: Analyze clips or process whole?
    if args.skip_analysis:
        print("⏩ Skipping analysis, processing entire video...")
        # --output is documented as "directory or file". When it names a
        # directory we still need a filename: passing the directory through
        # ends up in os.remove() on it further down and dies with EACCES.
        output_file = args.output
        if (not output_file or os.path.isdir(output_file)
                or output_file.endswith(("/", os.sep))):
            output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
        if not render_clip(input_video, output_file, output_format):
            raise RuntimeError('Whole-video render did not finish')
        reference_info=export_quality.probe(input_video)
        rv,_=export_quality.streams(reference_info)
        size=(rv['width'],rv['height'])
        if output_format != 'horizontal':
            from reframe_v2 import delivery_size
            size=delivery_size(*size,1.0 if output_format=='square' else ASPECT_RATIO)
        export_quality.enforce(output_file,'whole_video',
            export_quality.expectations(reference_info,size=None if output_format=='horizontal' else size),reference=input_video,master_audio=True)
    else:
        # Get duration (needed by both the transcript and the vision path).
        cap = cv2.VideoCapture(input_video)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        cap.release()

        # 3. Transcribe — unless the video has no audio, in which case fall back
        # to Gemini vision (picks clips from the imagery instead of the speech).
        from transcribe_backends import NoAudioError
        transcript = None
        # Module handover (issue #68): another module already transcribed this
        # exact source with the same backend, so reuse its output. Any problem
        # with the file falls back to transcribing normally rather than failing.
        if args.transcript:
            try:
                with open(args.transcript, 'r') as f:
                    transcript = json.load(f)
                if not transcript.get('segments'):
                    raise ValueError("transcript has no segments")
                print(f"⏩ Reusing precomputed transcript "
                      f"({len(transcript['segments'])} segments) — skipping transcription.")
            except Exception as e:
                print(f"⚠️ Could not use precomputed transcript ({e}) — transcribing normally.")
                transcript = None
        if transcript is None:
            transcript = load_transcript_checkpoint(output_dir, input_video, duration)
            if transcript is not None:
                print(f"♻️ Reusing the transcript from the interrupted run "
                      f"({len(transcript['segments'])} segments) — skipping transcription.")
        shared_asr=None;shared_asr_verified=False
        try:
            from category_intelligence import source_transcript_cache
            shared_asr=source_transcript_cache(input_video,duration)
            if transcript is None and shared_asr:
                cached=shared_asr[0].read('media-index',shared_asr[1])
                if isinstance(cached,dict) and isinstance(cached.get('segments'),list) and cached['segments']:
                    transcript=cached
                    shared_asr_verified=True
                    print('♻️ Reusing precomputed transcript from the source cache — skipping transcription.')
        except Exception:shared_asr=None
        if transcript is None:
            try:
                transcript = transcribe_video(input_video)
                shared_asr_verified=True
                save_transcript_checkpoint(output_dir, transcript, input_video, duration)
            except NoAudioError as e:
                print(f"🔇 {e} — switching to visual analysis.")
        if shared_asr and shared_asr_verified and transcript is not None:
            try:
                if len(json.dumps(transcript))<8*1024*1024:shared_asr[0].write('media-index',shared_asr[1],transcript)
            except Exception:pass

        # Music-only or wordless footage transcribes to a handful of words.
        # Clip it by what is on screen instead, like a video with no audio.
        if transcript is not None and speech_is_sparse(transcript, duration) and not os.getenv('ANALYSIS_MODE','').startswith('adaptive-'):
            n_words = sum(len((sg.get("text") or "").split()) for sg in transcript["segments"])
            print(f"🔇 Only {n_words} word(s) of speech in {duration:.0f}s — "
                  f"switching to visual analysis.")
            transcript = None

        # 4. Video-wide analysis is opt-in; highlights require all chapters.
        mode = os.getenv("GENERATION_MODE", "clips")
        hybrid = os.getenv("ANALYSIS_MODE", "transcript") == "hybrid"
        import adaptive_analysis
        adaptive=adaptive_analysis.enabled()
        analysis = None
        analysis_status=dict(status='requested' if adaptive or hybrid or mode=='highlights' else 'not_requested',
                             visual_available=False,editing_cues=0)
        if adaptive:
            analysis=adaptive_analysis.analyze(input_video,transcript,duration,output_dir)
            analysis_status.update(status='adaptive_completed',visual_available=any(
                m.get('verification_status')=='model_observed' for m in analysis['moments']),
                editing_cues=sum(len(s.get('editing_cues',[])) for s in analysis['scene_observations']),
                limitations=analysis.get('limitations',[]))
        elif hybrid or mode == "highlights":
            try:
                analysis = story_director.analyze_source(input_video, transcript, duration, output_dir)
                analysis_status.update(status='completed',visual_available=True,
                    editing_cues=sum(len(m.get('editing_cues',[])) for m in (analysis.get('scene_observations') or analysis.get('moments',[]))))
            except gemini_worker.GeminiBlockedError:
                raise
            except Exception as exc:
                analysis_status.update(status='fallback',error_type=type(exc).__name__)
                if hybrid:
                    failure_path=os.path.join(output_dir,'analysis_failure.json')
                    if not os.path.isfile(failure_path):
                        story_director.atomic_json(failure_path,{
                            **story_director.analysis_failure(exc),
                            'status':'failed','requested_mode':'hybrid'})
                    raise RuntimeError('Hybrid visual analysis failed after recovery attempts. No transcript-only clips were generated. Completed analysis checkpoints were kept; see analysis_failure.json for details. Retry this job or explicitly choose transcript mode.') from None
                if mode == "highlights" and not transcript:
                    raise RuntimeError(f"Cannot summarize the whole source: {exc}") from exc
                print(f"⚠️ Visual analysis unavailable; using transcript selection: {exc}")
        if adaptive:
            clips_data={'shorts':analysis.get('summary_shorts',analysis['moments']),'story_analysis':analysis}
        elif mode == "highlights":
            model_name = llm_backend.model_name() if llm_backend.active() else (os.getenv("GEMINI_MODEL") or 'gemini-3.1-flash-lite')
            def ask_story(prompt, schema):
                return _run_gemini_stage(None, model_name, prompt, schema)
            clips_data = (story_director.plan_summary(
                analysis, transcript, duration, float(os.getenv("SUMMARY_SECONDS", "60")), ask_story)
                if analysis else story_director.fallback_highlights(transcript,duration,float(os.getenv('SUMMARY_SECONDS','60'))))
        else:
            from learning.highlight_ranking import source_identity as learning_source_identity
            clips_data = get_viral_clips(transcript, duration, analysis, output_dir,
                learning_source_identity(input_video)) if transcript is not None else (
                {"shorts": analysis['moments']} if analysis else get_visual_clips(input_video, duration))
            if analysis:
                bounds = clip_duration_bounds()
                combined = (clips_data or {}).get('shorts', []) + analysis['moments']
                _, limit = clip_count_targets(10)
                if os.getenv('CLIP_STORY_AWARE','1')!='0':
                    combined=clip_selection.select_story_candidates(combined,transcript,duration,*bounds,
                        limit,analysis['moments'],target=export_quality.number(os.getenv('CLIP_TARGET_SECONDS')),
                        learning_context=dict(source_group=learning_source_identity(input_video)['sha256'],kind=os.getenv('AMCE_CATEGORY','general')))
                else:
                    combined=trim_to_best(story_director.validate_moments(combined,duration,*bounds),limit)
                clips_data = {**(clips_data or {}), "shorts": combined, "story_analysis": analysis}
        if os.getenv('CAPTION_PRESET')=='auto':
            import category_intelligence as ci
            selection=(analysis or {}).get('category_selection')
            if not selection and os.getenv('AMCE_CATEGORY','auto')!='auto':selection=ci.selection(os.environ['AMCE_CATEGORY'],{})
            if selection:
                os.environ['CAPTION_PRESET']=ci.editing_policy(selection['primary_category'],selection.get('subcategory','auto'))['caption_preset']
            else:os.environ['CAPTION_PRESET']='clean-minimal'
        if clips_data:
            clips_data['analysis_status']=analysis_status
        if clips_data and analysis:
            costs = [c for c in [clips_data.get('cost_analysis'), analysis.get('cost_analysis')] if c]
            clips_data['cost_analysis'] = {
                'model': os.getenv('GEMINI_MODEL', 'configured'),
                **{key: sum(c.get(key, 0) for c in costs)
                   for key in ('total_cost', 'input_tokens', 'output_tokens')}}

        if clips_data and clips_data.get('shorts') and os.getenv('PACING_ENABLED','1')!='0' and os.getenv('CLIP_STORY_AWARE','1')!='0':
            clips_data['shorts'],rejected=pacing.prepare_clips(clips_data['shorts'],transcript,duration,input_video,output_dir,analysis)
            if rejected:clips_data['pacing_rejected']=rejected
            import smart_split
            clips_data['shorts']=smart_split.apply(clips_data['shorts'],transcript,duration,input_video,output_dir,analysis)
        if not clips_data or not clips_data.get('shorts'):
            if clips_data and clips_data.get('pacing_rejected'):
                reasons='; '.join(dict.fromkeys(row['reason'] for row in clips_data['pacing_rejected']))
                raise RuntimeError('No clips passed pacing validation: '+reasons)
            # Deliberately fail instead of reframing the whole video: that path
            # wrote no metadata.json, so app.py marked the job failed anyway
            # (app.py:1087) after burning GPU on a render nobody could see.
            raise RuntimeError(
                "Clip detection failed — the AI model did not return usable clips for this video.")
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} clips!")

            # Save metadata. Silent videos have no transcript → no subtitles,
            # which is correct (there's no speech to caption).
            clips_data['transcript'] = transcript or {"language": "none", "segments": []}
            # The clip editor's re-render path needs to find the source video
            # again and reproduce the render settings, so record both. The
            # basename is enough — the file sits in the job dir (URL jobs with
            # --keep-original) or in uploads/ (upload jobs).
            clips_data['source_video'] = os.path.basename(input_video)
            clips_data['output_format'] = output_format
            clips_data['generation_mode'] = mode
            clips_data['pipeline_state'] = 'rendering'
            clips_data['job_options'] = {k:v for k,v in os.environ.items() if k in (
                'VIDEO_TEMPLATE','GENERATION_MODE','ANALYSIS_MODE','AMCE_CATEGORY','AMCE_PROMPT',
                'AMCE_MAX_VIDEO_SECONDS','AMCE_MAX_VISUAL_REQUESTS','AMCE_MAX_INPUT_TOKENS','AMCE_MAX_JOB_SECONDS',
                'AMCE_MAX_RETRIES','AMCE_MAX_CANDIDATES','AMCE_MAX_TEXT_REQUESTS','AMCE_COST_CEILING','AMCE_INPUT_PRICE','AMCE_OUTPUT_PRICE',
                'SUMMARY_SECONDS','CAPTION_PRESET',
                'FFMPEG_ENCODER','FFMPEG_X264_PRESET','FFMPEG_NVENC_PRESET','FFMPEG_THREADS','RENDER_MAX_ENCODERS','CLIP_WORKERS','RENDER_STRICT_OVERLAYS',
                'QUALITY_PRESET','FRAMING_PRESET','AUTO_CAPTIONS','AUTO_HOOK','AUTO_HOOK_STYLE',
                'CLIP_TARGET_SECONDS','CLIP_MIN_SECONDS','CLIP_MAX_SECONDS','CLIP_TARGET_MIN','CLIP_TARGET_MAX','CLIP_STORY_AWARE','CLIP_SCORE_WEIGHTS','EDIT_DIRECTOR','EDIT_DIRECTOR_STRATEGY','STORY_MODE','STORY_AUDIO_ENERGY',
                'REFRAME_KEYFRAMES','REFRAME_SUBJECT_CONTEXT','REFRAME_OBJECT_CLASSES','SMART_REFRAME','REFRAME_OUTPUT_SIZE',
                'PACING_ENABLED','PACING_MODE','PACING_TRIM_SILENCE','PACING_ALLOW_INCOMPLETE_END',
                'AUDIO_MASTERING','AUDIO_NORMALIZE','AUDIO_PRESET','AUDIO_TARGET_LUFS','AUDIO_TRUE_PEAK',
                'AUDIO_FADE_SECONDS','AUDIO_NOISE_REDUCTION')}
            for index, clip in enumerate(clips_data['shorts']):
                clip['clip_index'] = index
                clip['clip_id'] = f'clip_{index+1}'
                if os.getenv('CLIP_STORY_AWARE','1')!='0' and not clip.get('ranking_report'):
                    clip.update(clip_ranking.rescore_clips([clip],transcript,
                        (analysis or {}).get('moments',[]))[0])
                clip['quality_required'] = True
            metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
            with open(metadata_file, 'w') as f:
                json.dump(clips_data, f, indent=2)
            print(f"   Saved metadata to {metadata_file}")

            # 5. Process clips in parallel: each worker cuts + renders one
            # clip. Renders are mostly ffmpeg subprocesses (parallelize well);
            # detector inference is serialized internally via DETECT_LOCK.
            def _process_one_clip(i, clip):
                start = clip['start']
                end = clip['end']
                print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")

                clip_filename = f"{video_title}_clip_{i+1}.mp4"
                clip_temp_path = os.path.join(output_dir, f"temp_{clip_filename}")
                clip_final_path = os.path.join(output_dir, clip_filename)

                try:
                    # ffmpeg cut — re-encoding for precision on strict seconds
                    import editing_director
                    import recut
                    director_video_args=None
                    if editing_director.enabled() and output_format!='horizontal':
                        from reframe_v2 import director_encoder
                        director_video_args=director_encoder(*get_video_resolution(input_video))
                    segments = (clip.get('recipe') or {}).get('segments')
                    caption_transcript = transcript
                    if segments:
                        import recut
                        recut.run_cut_concat(input_video, segments, clip_temp_path, output_dir,video_args=director_video_args,
                            continuous_audio=bool((clip.get('recipe') or {}).get('pacing_audio_continuity')))
                        caption_transcript = recut.virtual_transcript(transcript, segments)
                        start, end = 0.0, recut.total_duration(segments)
                    else:
                        if director_video_args is not None:
                            recut.run_cut_concat(input_video,[dict(start=start,end=end)],clip_temp_path,output_dir,
                                                 video_args=director_video_args)
                        else:cut_clip(input_video, clip_temp_path, start, end, i + 1)

                    reference_info = export_quality.probe(clip_temp_path)
                    rv, _ra = export_quality.streams(reference_info)
                    if output_format == 'horizontal':
                        export_size = None
                    else:
                        from reframe_v2 import delivery_size
                        export_size = delivery_size(rv['width'], rv['height'],
                            1.0 if output_format == 'square' else ASPECT_RATIO)
                    clip['quality_expected'] = export_quality.expectations(
                        reference_info, duration=end-start, size=export_size,
                        speech_expected=bool((caption_transcript or {}).get('segments')))

                    import editing_director
                    if editing_director.enabled() and output_format!='horizontal':
                        selected=segments or [dict(start=clip['start'],end=clip['end'])]
                        director_context=dict(source_path=input_video,source_duration=duration,
                            source_identity=editing_director.identity(input_video),segments=selected,
                            transcript=transcript or {},analysis=analysis or {},
                            pacing_audio_continuity=bool((clip.get('recipe') or {}).get('pacing_audio_continuity')))
                        success=render_clip(clip_temp_path,clip_final_path,output_format,director_context=director_context)
                    else:success = render_clip(clip_temp_path, clip_final_path, output_format)
                    if not success:
                        raise RuntimeError('Clip render did not finish')
                    # Layer order: watermark burns into the canonical (so any
                    # later hook replacement, which re-derives from it, keeps
                    # the branding), the hook is a derived hooked_ file, and
                    # captions go last on top of whichever is current. Each
                    # worker writes only its own clip dict, so the re-dump
                    # after the pool is race-free.
                    if success and os.environ.get("WATERMARK") == "1":
                        apply_watermark(clip_final_path)
                    deliver_path = clip_final_path
                    # Which stretches were stacked (SPLIT): captions go on the
                    # seam there, and /api/subtitle needs it again later.
                    import layout_ranges as _layouts
                    clip['layout_ranges'] = _layouts.read(clip_final_path)
                    import video_templates
                    template=video_templates.selected(os.getenv('VIDEO_TEMPLATE'),clip)
                    directed_plan=None
                    if editing_director.enabled() and output_format!='horizontal':
                        directed_plan=editing_director.load(clip_final_path)
                        clip['edit_decision_file']=os.path.basename(clip_final_path)+'.edit.json'
                        clip['editing_strategy']=directed_plan['kind']
                    if template:
                        mapped=__import__('recut').virtual_transcript(caption_transcript,[dict(start=start,end=end)])
                        template_text=video_templates.initial_content(template,mapped,end-start)
                        if os.getenv('AUTO_HOOK','0')!='1':template_text['headline']['text']=''
                        captioned=os.path.join(output_dir,f'subtitled_{time.time_ns()}_{os.path.basename(clip_final_path)}')
                        import auto_edit
                        settings=(directed_plan or {}).get('auto_edit')
                        effect_path=captioned+'.effects.mp4'
                        template_clean=clip_final_path
                        try:
                            if settings:
                                template_clean=auto_edit.render(clip_final_path,effect_path,settings,
                                    (directed_plan['output_width'],directed_plan['output_height']),directed_plan['fps'],
                                    __import__('reframe_v2')._run,__import__('reframe_v2').director_encoder(directed_plan['output_width'],directed_plan['output_height']))
                                mapped=auto_edit.emphasize(mapped,settings)
                            video_templates.render(template_clean,captioned,template,mapped,end-start,
                                text=template_text,ranges=clip['layout_ranges'],captions=os.getenv('AUTO_CAPTIONS','1')!='0',auto_effects=auto_edit.active(settings))
                        finally:
                            if os.path.isfile(effect_path):os.remove(effect_path)
                        clip.update(video_template=template,template_content=template_text,
                            template_captions_enabled=os.getenv('AUTO_CAPTIONS','1')!='0',delivered_file=os.path.basename(captioned))
                        clip['quality_report']=export_quality.enforce(captioned,clip['clip_id'],clip['quality_expected'],
                            reference=clip_temp_path,master_audio=True,audio_config=video_templates.audio_settings(template),
                            transitions=[r['start'] for r in clip['layout_ranges']])
                        print('CLIP_QUALITY '+json.dumps(clip['quality_report'],ensure_ascii=False))
                        print(f'CLIP_READY {i} {clip["delivered_file"]}')
                        clip['render_status']='completed'
                        return True
                    if editing_director.enabled() and output_format!='horizontal':
                        plan=editing_director.load(clip_final_path)
                        clip['edit_decision_file']=os.path.basename(clip_final_path)+'.edit.json'
                        clip['editing_strategy']=plan['kind']
                        if plan['hook']['enabled']:
                            clip['auto_hook']=dict(text=plan['hook']['text'],style=plan['hook']['style'],position='top',
                                duration_seconds=plan['hook']['end'],start_seconds=plan['hook']['start'],
                                animation=plan['hook']['animation'],y=plan['hook']['y'],kind=plan['hook']['kind'])
                        captioned=os.path.join(output_dir,f'subtitled_{int(time.time())}_{os.path.basename(clip_final_path)}')
                        made=editing_director.render_layers(clip_final_path,captioned,plan)
                        if not made:
                            os.remove(captioned);captioned=clip_final_path
                        clip['delivered_file']=os.path.basename(captioned)
                        clip['director_delivery_file']=clip['delivered_file']
                        clip['quality_report']=export_quality.enforce(captioned,clip['clip_id'],clip['quality_expected'],
                            reference=clip_temp_path,master_audio=True,transitions=[r['start'] for r in clip['layout_ranges']])
                        print('CLIP_QUALITY '+json.dumps(clip['quality_report'],ensure_ascii=False))
                        print(f'CLIP_READY {i} {clip["delivered_file"]}')
                        clip['render_status']='completed'
                        return True
                    # The hook was written from the transcript alone. When the
                    # render put this clip's meaning on the screen, rewrite hook
                    # and title from three of its frames BEFORE burning them.
                    if success and hook_grounding.wanted(clip['layout_ranges'], end - start):
                        hook_grounding.reground(clip_final_path, clip, caption_transcript, start, end)
                    if success and os.environ.get("AUTO_HOOK") == "1":
                        hooked = auto_hook_clip(clip_final_path, clip, caption_transcript, start, end)
                        if hooked:
                            deliver_path, clip['auto_hook'] = hooked
                    if success:
                        captioned = auto_caption_clip(
                            deliver_path, caption_transcript, start, end,
                            split_ranges=_layouts.split_ranges(clip['layout_ranges']),
                            editorial_ranges=_layouts.editorial_ranges(clip['layout_ranges']))
                        import render_runtime
                        render_runtime.require_captions(caption_transcript,start,end,
                            os.getenv('AUTO_CAPTIONS','1')!='0',bool(captioned))
                        clip['delivered_file'] = os.path.basename(captioned or deliver_path)
                        clip['quality_report'] = export_quality.enforce(
                            captioned or deliver_path, clip['clip_id'], clip['quality_expected'],
                            reference=clip_temp_path,master_audio=True,
                            transitions=[r['start'] for r in clip['layout_ranges']])
                        print('CLIP_QUALITY ' + json.dumps(clip['quality_report'], ensure_ascii=False))
                        print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
                        # Hand the API the file to actually serve for this clip.
                        # Without it the status poller guesses the clean reframe
                        # name, so a job in flight showed every clip stripped of
                        # its hook and captions until the WHOLE job finished and
                        # the result got rebuilt through _canonical_clip_file.
                        # Printed only after the full chain (reframe, watermark,
                        # hook, captions) so the file is complete when it is
                        # announced, never one that ffmpeg is still writing.
                        print(f"CLIP_READY {i} "
                              f"{os.path.basename(captioned or deliver_path)}")
                    clip['render_status'] = 'completed' if success else 'failed'
                    if success:
                        clip['delivered_file'] = os.path.basename(captioned or deliver_path)
                    return success
                except export_quality.QualityError as exc:
                    clip['quality_report'] = exc.report
                    print('CLIP_QUALITY ' + json.dumps(exc.report, ensure_ascii=False))
                    clip['render_status'] = 'failed'
                    raise
                except Exception:
                    clip['render_status'] = 'failed'
                    clip['quality_report'] = export_quality.validate(
                        clip_final_path, clip['clip_id'], clip.get('quality_expected'))
                    clip['quality_report'].update(status='FAIL',accepted=False)
                    clip['quality_report']['problems'].append({
                        'code':'RENDER_INCOMPLETE','severity':'FAIL','timestamps':[],
                        'message':'The render chain did not finish.',
                        'action':'Check the processing error and rerender this clip.'})
                    export_quality.save_report(clip_final_path,clip['quality_report'])
                    print('CLIP_QUALITY ' + json.dumps(clip['quality_report'], ensure_ascii=False))
                    raise
                finally:
                    if os.path.exists(clip_temp_path):
                        os.remove(clip_temp_path)

            import render_runtime
            clip_workers = render_runtime.limits()['clip_workers']
            def render_worker(i,clip):
                def measured(row):
                    print('RENDER_PROGRESS '+json.dumps(dict(clip_index=i,**row)),flush=True)
                with render_runtime.progress_scope(measured):return _process_one_clip(i,clip)
            shorts = clips_data['shorts']
            with ThreadPoolExecutor(max_workers=min(clip_workers, len(shorts))) as pool:
                futures = {pool.submit(render_worker, i, clip): i
                           for i, clip in enumerate(shorts)}
                for future in as_completed(futures):
                    i = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"   ❌ Clip {i+1} failed: {type(e).__name__}: {e}")

            # Completion is explicit; metadata alone is not proof of rendered files.
            clips_data['pipeline_state'] = 'completed' if any(
                c.get('render_status') == 'completed' for c in shorts) else 'failed'
            story_director.atomic_json(metadata_file, clips_data)

    # Clean up original if requested
    if args.url and not args.keep_original and os.path.exists(input_video):
        os.remove(input_video)
        print(f"🗑️  Cleaned up downloaded video.")
    # The job finished: a later run in this directory must transcribe afresh.
    if not args.skip_analysis:
        clear_transcript_checkpoint(output_dir)

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
