using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace AnsGarage
{
    public static class Core
    {
        // The version of An's Garage (shared with An's Garage for Blender); the only place it is written.
        public const string Version = "1.1.9";
        public static string Normalize(string value) { return (value ?? "").Replace('\\', '/').Trim('/'); }
        public static bool InScope(string name, string prefix)
        {
            name = Normalize(name); prefix = Normalize(prefix);
            return prefix.Length > 0 && (name.Equals(prefix, StringComparison.OrdinalIgnoreCase) || name.StartsWith(prefix + "/", StringComparison.OrdinalIgnoreCase));
        }
        public static string SafeName(string value)
        {
            string s = new string((value ?? "unnamed").Select(c => char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_').ToArray());
            return "p_" + s.Substring(0, Math.Min(s.Length, 48));
        }
        public static string Id(string value)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-", "").ToLowerInvariant();
        }
        // Row vectors: right, up, forward, translation. Only proper rigid matrices can
        // be faithfully passed through this version of the upstream FBX exporter.
        public static bool IsRigid(double[] m)
        {
            if (m == null || m.Length != 12 || m.Any(x => double.IsNaN(x) || double.IsInfinity(x))) return false;
            const double eps = 0.00001;
            for (int i = 0; i < 3; ++i)
                for (int j = i; j < 3; ++j)
                {
                    double dot = 0; for (int k = 0; k < 3; ++k) dot += m[i * 3 + k] * m[j * 3 + k];
                    if (Math.Abs(dot - (i == j ? 1 : 0)) > eps) return false;
                }
            double det = m[0] * (m[4]*m[8]-m[5]*m[7]) - m[1]*(m[3]*m[8]-m[5]*m[6]) + m[2]*(m[3]*m[7]-m[4]*m[6]);
            return Math.Abs(det - 1) < eps;
        }
        public static string PendingFbxPath(string file)
        {
            // The FBX SDK appends .fbx when given an unfamiliar final extension.
            return Path.Combine(Path.GetDirectoryName(file), Path.GetFileNameWithoutExtension(file) + ".partial.fbx");
        }
        public static string FbxStagingPath(string file)
        {
            // The native FBX writer can't open a path with non-ASCII characters (e.g. a "Murciélago" export folder): it
            // writes nothing. Such files are written in a plain temporary folder first, then moved into place.
            string partial = PendingFbxPath(file);
            if (IsAscii(partial)) return partial;
            foreach (string root in new[] { Path.GetTempPath(), Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData) })
            {
                if (string.IsNullOrEmpty(root) || !IsAscii(root)) continue;
                string dir = Path.Combine(root, "AnsGarage", "fbx");
                Directory.CreateDirectory(dir);
                return Path.Combine(dir, Guid.NewGuid().ToString("N") + ".partial.fbx");
            }
            throw new IOException("The FBX writer needs a folder without accented letters; the temporary folder has some: " + Path.GetTempPath());
        }
        public static bool IsAscii(string value) { return value.All(c => c < 128); }
        public static bool HasBinaryFbxHeader(string file)
        {
            if (!File.Exists(file) || new FileInfo(file).Length < 27) return false;
            using (var s = File.OpenRead(file))
            {
                byte[] b = new byte[23]; s.Read(b, 0, b.Length);
                return Encoding.ASCII.GetString(b) == "Kaydara FBX Binary  \0\x1a\0";
            }
        }
    }
}
