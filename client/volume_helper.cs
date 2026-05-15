using System;
using System.Runtime.InteropServices;
public class V{
 [ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
 class Enum{}

 [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IEnum{
  void X1();
  void GetDefault(int df,int rl,out object dev);
 }

 [Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IDev{
  void Activate(ref Guid iid,int cls,IntPtr p,out object vol);
 }

 [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IVol{
  int RegisterControlChangeNotify(IntPtr cb);
  int UnregisterControlChangeNotify(IntPtr cb);
  int GetChannelCount(out uint c);
  int SetMasterVolumeLevel(float db,ref Guid g);
  int SetMasterVolumeLevelScalar(float f,ref Guid g);
  int GetMasterVolumeLevel(out float db);
  int GetMasterVolumeLevelScalar(out float f);
  int SetChannelVolumeLevel(uint ch,float db,ref Guid g);
  int SetChannelVolumeLevelScalar(uint ch,float f,ref Guid g);
  int GetChannelVolumeLevel(uint ch,out float db);
  int GetChannelVolumeLevelScalar(uint ch,out float f);
  int SetMute(int m,ref Guid g);
  int GetMute(out int m);
  int GetVolumeStepInfo(out uint s,out uint sc);
  int VolumeStepUp(ref Guid g);
  int VolumeStepDown(ref Guid g);
  int QueryHardwareSupport(out uint h);
  int GetVolumeRange(out float min,out float max,out float inc);
 }

 static IVol GetVol(){
  var e=(IEnum)new Enum();
  object d;e.GetDefault(0,0,out d);
  var dev=(IDev)d;
  var iid=new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
  object v;dev.Activate(ref iid,0,IntPtr.Zero,out v);
  return(IVol)v;
 }

 public static void Main(string[] a){
  if(a.Length==0)return;
  try{
   var v=GetVol();
   var c=a[0].ToLower();
   Guid g=Guid.Empty;
   if(c=="get"){
    float f;v.GetMasterVolumeLevelScalar(out f);
    Console.Write((int)Math.Round(f*100));
   }else if(c=="mute"){
    int m;v.GetMute(out m);
    Console.Write(m);
   }else if(c=="set"&&a.Length>1){
    float f=float.Parse(a[1])/100f;
    v.SetMasterVolumeLevelScalar(f,ref g);
    Console.Write("OK");
   }else if(c=="setmute"&&a.Length>1){
    int m=int.Parse(a[1]);
    v.SetMute(m,ref g);
    Console.Write("OK");
   }else if(c=="test"){
    float f;v.GetMasterVolumeLevelScalar(out f);
    int m;v.GetMute(out m);
    Console.Write("VOL="+((int)Math.Round(f*100))+" MUTE="+m);
   }
  }catch(Exception ex){
   Console.Write("ERR:"+ex.Message);
  }
 }
}
