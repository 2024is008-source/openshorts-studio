using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging.Abstractions;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
using OpenShorts.Infrastructure;
using Xunit;
namespace OpenShorts.Tests;

public sealed class ProviderTransport
{
    [Fact]public async Task MultipartAndProviderRequestsStayOnOwnedAuthenticatedOrigin()
    {
        var source=Environment.GetEnvironmentVariable("OPENSHORTS_TEST_ROOT");if(source is null)return;
        var directory=Path.Combine(Path.GetTempPath(),"openshorts-provider-transport-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
        try
        {
            var contract=new JsonObject{["protocol_version"]=1,["editor_project_version"]=1,
                ["features"]=new JsonArray(NativeContract.RequiredFeatures.Select(x=>(JsonNode?)JsonValue.Create(x)).ToArray()),
                ["routes"]=new JsonArray(NativeContract.RequiredRoutes.Select(x=>{var p=x.Split(' ',2);return (JsonNode)new JsonObject{["method"]=p[0],["path"]=p[1]};}).ToArray())};
            File.WriteAllText(Path.Combine(directory,"contract.json"),contract.ToJsonString());
            var script=Path.Combine(directory,"server.py");File.WriteAllText(script,"""
import os,json
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from email.parser import BytesParser
from email.policy import default
root=Path(__file__).parent
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self):
  if self.headers.get('X-OpenShorts-Session')!=os.environ['OPENSHORTS_LOCAL_TOKEN']:
   self.send_response(403);self.end_headers();return
  body=self.rfile.read(int(self.headers.get('Content-Length','0')))
  parts={}
  if self.headers.get('Content-Type','').startswith('multipart/'):
   message=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
   for part in message.iter_parts():parts[part.get_param('name',header='content-disposition')]=part.get_payload(decode=True).decode()
  row={'path':self.path,'parts':parts,'eleven':self.headers.get('X-ElevenLabs-Key'),'fal':self.headers.get('X-Fal-Key')}
  with (root/'requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
  result=json.loads((root/'contract.json').read_text()) if self.path=='/api/desktop/contract' else {'ok':True,'session_id':'session-test'}
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(result).encode())
 do_GET=reply
 do_POST=reply
 do_DELETE=reply
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
Path(os.environ['OPENSHORTS_READY_FILE']).write_text(str(server.server_port))
server.serve_forever()
""");
            var store=new UserStorage(Path.Combine(directory,"library"),Path.Combine(directory,"profile"));
            await using var bridge=new EngineClient(store,new ServerLauncher(Path.Combine(source,".venv","Scripts","python.exe"),script),new(source),NullLogger<EngineClient>.Instance);
            await bridge.StartAsync();
            var image=Path.Combine(directory,"fixture.png");File.WriteAllText(image,"test-image-bytes");
            await bridge.FormAsync("/api/thumbnail/analyze",new Dictionary<string,string>{["session_id"]="test"},image);
            await bridge.FormAsync("/api/thumbnail/generate",new Dictionary<string,string>{["title"]="Example"},images:new Dictionary<string,string>{["face"]=image});
            await bridge.SendAsync("/api/translate",new(){["job_id"]="test",["clip_index"]=0,["target_language"]="es"},providerHeaders:new Dictionary<string,string>{["X-ElevenLabs-Key"]="test-private-key"});
            await bridge.GetAsync("/api/social/analytics",query:new Dictionary<string,string>{["user"]="profile&a=b"});
            await bridge.GetAsync("/api/desktop/projects");
            await bridge.CancelScheduledAsync("scheduled-1","profile&a=b","test-upload-key");
            await Assert.ThrowsAsync<ArgumentException>(()=>bridge.SendAsync("/api/translate",new(),providerHeaders:new Dictionary<string,string>{["X-OpenShorts-Session"]="override"}));
            var rows=File.ReadAllLines(Path.Combine(directory,"requests.jsonl")).Select(x=>JsonNode.Parse(x)!).ToArray();
            var form=rows.Single(x=>x["path"]!.ToString()=="/api/thumbnail/analyze");Assert.Equal("test-image-bytes",form["parts"]!["file"]!.ToString());Assert.Equal("test",form["parts"]!["session_id"]!.ToString());
            Assert.Equal("test-private-key",rows.Single(x=>x["path"]!.ToString()=="/api/translate")["eleven"]!.ToString());
            Assert.Null(rows.Single(x=>x["path"]!.ToString()=="/api/desktop/projects")["eleven"]);
            Assert.Contains(rows,x=>x["path"]!.ToString()=="/api/social/analytics?user=profile%26a%3Db");
            Assert.Contains(rows,x=>x["path"]!.ToString()=="/api/social/scheduled/scheduled-1?user=profile%26a%3Db");
            Assert.Equal("test-image-bytes",rows.Single(x=>x["path"]!.ToString()=="/api/thumbnail/generate")["parts"]!["face"]!.ToString());
        }
        finally{if(Directory.Exists(directory))Directory.Delete(directory,true);}
    }
    private sealed class ServerLauncher(string python,string script):IWorkerLauncher
    {public IWorkerProcess Start(string executable,IReadOnlyList<string> arguments,string directory,IDictionary<string,string> environment)=>new WindowsWorkerLauncher().Start(python,[script],directory,environment);}
}
