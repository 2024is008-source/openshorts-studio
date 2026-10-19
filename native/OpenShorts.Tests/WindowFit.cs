using OpenShorts.Desktop;
using Xunit;

namespace OpenShorts.Tests;
public sealed class WindowFit
{
    [Theory]
    [InlineData(1920,1032,1.25)]
    [InlineData(1366,720,1.0)]
    [InlineData(1366,720,1.5)]
    [InlineData(1920,1032,2.0)]
    public void OversizedWindowFitsScaledDisplay(int width,int height,double scale)
    {
        var fit=WindowGeometry.Fit(new(0,0,width,height),new(0,0,(int)(1600*scale),(int)(1000*scale)),true);
        Assert.True(fit.Left>=0 && fit.Top>=0);
        Assert.True(fit.Left+fit.Width<=width && fit.Top+fit.Height<=height);
        Assert.Equal((width-fit.Width)/2,fit.Left);
    }
    [Fact] public void NegativeMonitorCoordinatesArePreserved()
    {
        var fit=WindowGeometry.Fit(new(-1920,-200,1920,1040),new(-2200,-500,1600,1000),false);
        Assert.Equal(-1920,fit.Left);Assert.Equal(-200,fit.Top);
    }
    [Fact] public void ValidUserPositionIsPreserved()
    {
        var bounds=new WindowBounds(140,100,1000,700);
        Assert.Equal(bounds,WindowGeometry.Fit(new(0,0,1920,1032),bounds,false));
    }
}
