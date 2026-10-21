using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

// Shows the exporter's dialogs (DPI-aware, like inside Frosty) and saves screenshots. No game data is read.
class DialogShot {
 [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
 static string plugin, editor;
 [STAThread]
 static void Main(string[] a) {
  plugin = a[0]; editor = a[1];
  AppDomain.CurrentDomain.AssemblyResolve += (s, e) => {
   var name = new AssemblyName(e.Name).Name;
   foreach (var dir in new[] { plugin, editor, Path.Combine(editor, "Plugins") }) { var p = Path.Combine(dir, name + ".dll"); if (File.Exists(p)) return Assembly.LoadFrom(p); }
   return null; };
  SetProcessDPIAware();
  Application.EnableVisualStyles();
  Run(a[2]);
 }
 static void Run(string outDir) {
  var asm = Assembly.LoadFrom(Path.Combine(plugin, "AnsGarage.dll"));
  foreach (var type in new[] { "AnsGarage.Options", "AnsGarage.VehiclePicker" }) {
   var form = (Form)Activator.CreateInstance(asm.GetType(type, true), true);
   form.Shown += (s, e) => {
    var t = new Timer { Interval = 1500 };
    t.Tick += (s2, e2) => {
     t.Stop();
     using (var bmp = new Bitmap(form.Width, form.Height)) {
      form.DrawToBitmap(bmp, new Rectangle(0, 0, form.Width, form.Height));
      bmp.Save(Path.Combine(outDir, type.Substring(type.LastIndexOf('.') + 1) + ".png"));
     }
     Console.WriteLine(type + " " + form.Width + "x" + form.Height + " dpi " + form.DeviceDpi);
     form.Hide(); form.Close();
    };
    t.Start();
   };
   try { form.ShowDialog(); } catch (Exception ex) { Console.WriteLine(type + " " + ex.Message); }
  }
 }
}
