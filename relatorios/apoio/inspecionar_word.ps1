$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class WordEvapoWindowAudit {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc p, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    public static string Label(IntPtr h) {
        var t=new StringBuilder(1024); var c=new StringBuilder(256);
        GetWindowText(h,t,t.Capacity); GetClassName(h,c,c.Capacity);
        return h.ToInt64()+" "+c+" "+t;
    }
    public static string[] Read(uint pid) {
        var result=new List<string>();
        EnumWindows((h,l)=> { uint p; GetWindowThreadProcessId(h,out p);
            if(p==pid) { result.Add(Label(h)); EnumChildWindows(h,(ch,cl)=>{var a=Label(ch); if(a.Length>0) result.Add(a); return true;},IntPtr.Zero); }
            return true;},IntPtr.Zero);
        return result.ToArray();
    }
}
'@
Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object {
    $_ | Select-Object Id,StartTime,CPU
    [WordEvapoWindowAudit]::Read([uint32]$_.Id)
}
