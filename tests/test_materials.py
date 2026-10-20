import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("materials", Path(__file__).parents[1] / "blender/unbound_materials.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def ref(node):
    return {"Kind": "External", "Node": node}


def parameter(name, x=1):
    return {"ParameterName": {"Type": "CString", "Value": name},
            "Value": {"x": x, "y": 0, "z": 0, "w": 0}}


def document():
    return {"Schema": 1, "Textures": [], "Meshes": [], "Nodes": [
        {"Id": "graph", "Type": "ShaderGraph", "Asset": "vehicles/shaders/cs_pbr_tire_max_lookdev", "Raw": {}},
        {"Id": "preset", "Type": "SurfaceShaderPreset", "Asset": "preset", "Raw":
            {"ShaderPreset": {"Shader": ref("graph"), "VectorParameters": [parameter("Metalness", .5)]}}},
        {"Id": "base", "Type": "MeshMaterial", "Asset": "mesh", "Raw":
            {"Shader": {"Shader": ref("preset"), "VectorParameters": [parameter("METALNESS", .2)]}}},
        {"Id": "override", "Type": "MeshMaterialVariation", "Asset": "db", "Raw":
            {"Shader": {"Shader": {"Kind": "Null"}, "VectorParameters": [parameter("roughness", .7)]}}},
    ]}


class MaterialsTests(unittest.TestCase):
    def test_uv_declaration_order_is_not_semantic_suffix(self):
        s = {"VertexAttributes": [
            {"Usage": "TexCoord3", "Format": "Half2", "StreamIndex": 1},
            {"Usage": "TexCoord1", "Format": "Half2", "StreamIndex": 0},
            {"Usage": "MaskUv", "Format": "Short2N", "StreamIndex": 0},
            {"Usage": "TexCoord0", "Format": "Half2", "StreamIndex": 1}]}
        self.assertEqual([(b["SourceUsage"], b["BlenderLayer"]) for b in m.uv_bindings(s)],
                         [("TexCoord1", "UVChannel0"), ("MaskUv", "MaskUv"),
                          ("TexCoord3", "UVChannel2"), ("TexCoord0", "UVChannel3")])

    def test_radiosity_consumes_ordinal_displacement_does_not(self):
        s = {"VertexAttributes": [{"Usage": u, "Format": "Half2"} for u in
                                 ("RadiosityTexCoord", "DisplacementMapTexCoord", "TexCoord5")]}
        self.assertEqual([b["BlenderLayer"] for b in m.uv_bindings(s)], ["RadiosityTexCoord", "UVChannel1"])

    def test_nested_preset_then_case_insensitive_instance_override(self):
        r = m.Resolver(document())
        state = r.resolve({}, {"Index": 0, "Source": ref("base")})
        self.assertEqual(state["Parameters"]["VectorParameters"]["metalness"]["Value"]["x"], .2)
        self.assertEqual(state["Shader"]["Node"], "graph")

    def test_null_shader_inherits_base(self):
        r = m.Resolver(document())
        variant = {"Assignments": [{"Slots": [0], "Material": ref("base"), "Override": ref("override")}]}
        state = r.resolve({}, {"Index": 0, "Source": ref("base")}, variant)
        self.assertEqual(set(state["Parameters"]["VectorParameters"]), {"metalness", "roughness"})

    def test_shader_replacement_clears_old_parameters(self):
        d = document()
        d["Nodes"][-1]["Raw"]["Shader"]["Shader"] = ref("graph")
        variant = {"Assignments": [{"Slots": [0], "Material": ref("base"), "Override": ref("override")}]}
        state = m.Resolver(d).resolve({}, {"Index": 0, "Source": ref("base")}, variant)
        self.assertEqual(set(state["Parameters"]["VectorParameters"]), {"roughness"})

    def test_conflicting_root_rows_do_not_pick_first(self):
        d = document()
        variant = {"Hash": "00000000", "Assignments": [{"Slots": [0], "Material": ref("base"), "Override": ref("override")}]}
        other = copy.deepcopy(variant)
        other["Assignments"] = []
        state, _, status = m.Resolver(d).choose_root({"Variants": [variant, other]}, {"Index": 0, "Source": ref("base")})
        self.assertEqual(status, "ambiguous_root_db_base_preserved")
        self.assertNotIn("roughness", state["Parameters"]["VectorParameters"])

    def test_wrong_material_identity_is_rejected(self):
        variant = {"Assignments": [{"Slots": [0], "Material": ref("wrong"), "Override": ref("override")}]}
        with self.assertRaises(ValueError):
            m.Resolver(document()).resolve({}, {"Index": 0, "Source": ref("base")}, variant)

    def test_cycle_and_missing_graph_rejected(self):
        d = document()
        d["Nodes"][1]["Raw"]["ShaderPreset"]["Shader"] = ref("preset")
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            m.Resolver(d).resolve({}, {"Index": 0, "Source": ref("base")})
        d["Nodes"][1]["Raw"]["ShaderPreset"]["Shader"] = ref("missing")
        with self.assertRaisesRegex(ValueError, "Missing"):
            m.Resolver(d).resolve({}, {"Index": 0, "Source": ref("base")})

    def test_packing_does_not_imply_uv_or_colorspace(self):
        d = document()
        d["Nodes"][2]["Raw"]["Shader"]["TextureParameters"] = [
            {"ParameterName": name, "Value": ref("absent")} for name in ("RGB_Color_A_Smoothness", "T_Material")]
        state = m.Resolver(d).resolve({}, {"Index": 0, "Source": ref("base")})
        bindings = state["TextureBindings"]
        self.assertEqual(bindings[0]["Channels"]["A"], "Smoothness")
        self.assertIsNone(bindings[0]["SourceUvUsage"])
        self.assertEqual(bindings[0]["ColorSpace"], "unspecified")
        self.assertIsNone(bindings[1]["Channels"])

    def test_displacement_explicit_uv_is_retained(self):
        d = document()
        d["Nodes"][2]["Raw"].update(DisplacementMap=ref("not_exported"), DisplacementMapTexCoord=3)
        binding = m.Resolver(d).resolve({}, {"Index": 0, "Source": ref("base")})["TextureBindings"][0]
        self.assertEqual(binding["SourceUvUsage"], "TexCoord3")
        self.assertEqual(binding["UvEvidence"], "MeshMaterial.DisplacementMapTexCoord")

    def test_explicit_uv_resolves_through_export_order(self):
        state = {"TextureBindings": [{"Parameter": "DisplacementMap", "SourceUvUsage": "TexCoord3",
                                     "UvEvidence": "MeshMaterial.DisplacementMapTexCoord"}]}
        section = {"VertexAttributes": [{"Usage": u, "Format": "Half2"} for u in ("TexCoord2", "TexCoord3")]}
        self.assertEqual(m.texture_uv_bindings(state, section)[0]["BlenderLayer"], "UVChannel1")
        self.assertEqual(m.texture_uv_bindings(state, {"VertexAttributes":[]})[0]["Status"], "source_uv_missing_from_geometry")


if __name__ == "__main__":
    unittest.main()
