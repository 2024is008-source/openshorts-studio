using System.Globalization;
using OpenShorts.Core;
using OpenShorts.Infrastructure;
using Xunit;
namespace OpenShorts.Tests;
public sealed class GenerationAndProviders
{
    [Fact]public void GenerationNumbersUseApiInvariantCulture()
    {
        var previous=CultureInfo.CurrentCulture;
        try{CultureInfo.CurrentCulture=CultureInfo.GetCultureInfo("de-DE");var fields=new GenerationSettings{AudioFade=.25,TargetSeconds=32.5,OutputFormat="square"}.ToFields();Assert.Equal("0.25",fields["audio_fade_seconds"]!.GetValue<string>());Assert.Equal("32.5",fields["clip_target_seconds"]!.GetValue<string>());Assert.Equal("square",fields["output_format"]!.GetValue<string>());}
        finally{CultureInfo.CurrentCulture=previous;}
    }
    [Fact]public void GenerationRejectsUnsafeAndNonfiniteOptions()
    {Assert.Throws<ArgumentException>(()=>new GenerationSettings{TargetSeconds=double.NaN}.ToFields());Assert.Throws<ArgumentException>(()=>new GenerationSettings{Framing="filter=file"}.ToFields());Assert.Throws<ArgumentException>(()=>new GenerationSettings{TargetClips=0}.ToFields());}
    [Fact]public void ProviderSecretsAreSeparatedAndEncrypted()
    {
        var root=Path.Combine(Path.GetTempPath(),"openshorts-providers-"+Guid.NewGuid().ToString("N"));
        try
        {
            var storage=new UserStorage(Path.Combine(root,"library"),Path.Combine(root,"profile"));
            storage.SaveCredential("gemini-test");storage.SaveCredential("eleven-test","elevenlabs");storage.SaveCredential("fal-test","fal");
            Assert.Equal("gemini-test",storage.LoadCredential());Assert.Equal("eleven-test",storage.LoadCredential("elevenlabs"));
            Assert.DoesNotContain("eleven-test",System.Text.Encoding.UTF8.GetString(File.ReadAllBytes(Path.Combine(storage.Roaming,"elevenlabs.dpapi"))));
            Assert.Throws<ArgumentException>(()=>storage.SaveCredential("x","../escape"));storage.SaveCredential("","elevenlabs");Assert.Equal("",storage.LoadCredential("elevenlabs"));Assert.Equal("fal-test",storage.LoadCredential("fal"));
        }
        finally{if(Directory.Exists(root))Directory.Delete(root,true);}
    }
}
