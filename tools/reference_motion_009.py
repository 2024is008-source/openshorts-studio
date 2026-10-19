import pathlib,json,cv2,numpy as np
root=pathlib.Path.cwd()
for d in sorted((root/'build/reference-study-009').glob('ref-*')):
 m=json.loads((d/'measurements.json').read_text());cap=cv2.VideoCapture(m['file']);previous=None;rows=[]
 for t in np.arange(0,m['duration'],.2):
  cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,f=cap.read()
  if not ok:continue
  f=cv2.cvtColor(cv2.resize(f,(180,320)),cv2.COLOR_BGR2GRAY)
  if previous is not None:
   delta=float(np.abs(f.astype(float)-previous.astype(float)).mean());scale=None;inliers=0
   points=cv2.goodFeaturesToTrack(previous,maxCorners=60,qualityLevel=.02,minDistance=7)
   if points is not None and len(points)>=12:
    q,status,_=cv2.calcOpticalFlowPyrLK(previous,f,points,None)
    good=status.ravel()==1
    if good.sum()>=12:
     mat,mask=cv2.estimateAffinePartial2D(points[good],q[good],method=cv2.RANSAC,ransacReprojThreshold=2.)
     if mat is not None:
      inliers=int(mask.sum());scale=float(np.sqrt(mat[0,0]**2+mat[1,0]**2))
   rows.append(dict(start=round(float(t-.2),3),end=round(float(t),3),mean_absolute_luma_difference=round(delta,3),affine_scale=scale,inliers=inliers))
  previous=f
 cap.release();(d/'motion.json').write_text(json.dumps(rows,indent=2))
 reliable=[r for r in rows if r['inliers']>=20 and r['affine_scale'] is not None and .9<r['affine_scale']<1.1]
 still=[r['start'] for r in rows if r['mean_absolute_luma_difference']<.1]
 p=root/'docs/reference-study-009'/f'{d.name}.md'
 with p.open('a',encoding='utf-8') as out:
  out.write('\n\n### Additional local temporal motion measurement\n')
  out.write(f'5 Hz grayscale sampling at 180×320, at most 60 tracked corners per sample; {len(reliable)} adjacent pairs had at least 20 affine inliers. ')
  out.write('Affine scale is whole-image motion evidence, not proof of an editorial zoom or playback-speed change. ')
  if reliable:
   strongest=sorted(reliable,key=lambda r:abs(r['affine_scale']-1),reverse=True)[:4]
   out.write('Largest retained pair estimates: '+', '.join('{start:.2f}-{end:.2f}s x{affine_scale:.3f}'.format(**r) for r in strongest)+'. ')
  out.write(f'{len(still)} pairs had mean luma change <0.1/255. Static graphics/end cards can explain these; freeze-frame editing is UNKNOWN. Raw measurements: `../../build/reference-study-009/{d.name}/motion.json`.\n')
print('Temporal measurements complete')