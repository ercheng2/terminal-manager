using System;
using System.Runtime.InteropServices;
public class K{
 [ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
 class E{}

 [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IE{
  void X1();
  void G(int a,int b,out object d);
 }

 [Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface ID{
  void A(ref Guid i,int c,IntPtr p,out object v);
 }

 [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IV{
  int X0(IntPtr a);
  int X1(IntPtr a);
  int X2(out uint c);
  int X3(float a,ref Guid b);
  int X4(float a,ref Guid b);
  int X5(out float a);
  int X6(out float a);
  int X7(uint a,float b,ref Guid c);
  int X8(uint a,float b,ref Guid c);
  int X9(uint a,out float b);
  int X10(uint a,out float b);
  int X11(int a,ref Guid b);
  int X12(out int a);
  int X13(out uint a,out uint b);
  int X14(ref Guid a);
  int X15(ref Guid a);
  int X16(out uint a);
  int X17(out float a,out float b,out float c);
 }

 static IV GetV(){
  var e=(IE)new E();
  object d;
  e.G(0,0,out d);
  var dev=(ID)d;
  var iid=new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
  object v;
  dev.A(ref iid,0,IntPtr.Zero,out v);
  return(IV)v;
 }

 public static void Main(string[] a){
  if(a.Length==0)return;
  try{
   var v=GetV();
   var c=a[0].ToLower();
   Guid g=Guid.Empty;
   if(c=="get"){
    float f;v.X6(out f);
    Console.Write((int)Math.Round(f*100));
   }else if(c=="mute"){
    int m;v.X12(out m);
    Console.Write(m);
   }else if(c=="set"&&a.Length>1){
    float f=float.Parse(a[1])/100f;
    v.X4(f,ref g);
    Console.Write("OK");
   }else if(c=="setmute"&&a.Length>1){
    int m=int.Parse(a[1]);
    v.X11(m,ref g);
    Console.Write("OK");
   }else if(c=="test"){
    float f;v.X6(out f);
    int m;v.X12(out m);
    Console.Write("VOL="+((int)Math.Round(f*100))+" MUTE="+m);
   }
  }catch(Exception ex){
   Console.Write("ERR:"+ex.Message);
  }
 }
}
