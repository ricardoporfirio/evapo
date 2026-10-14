"""Conferência da planilha, fonte solar por cena e ausência de dupla correção."""

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from evapo.calculos.energia import calcular_radiacoes
from evapo.calculos.reflectancia import converter_reflectancia
from evapo.calculos.solar import (
    NOME_PLANILHA_SOLAR, distancia_terra_sol_data, fator_distancia_terra_sol,
    informacoes_solares,
)
from evapo.dados.metadados import descobrir_cenas


def criar_planilha(caminho):
    """Workbook mínimo com valores salvos da planilha fornecida pelo usuário."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(caminho, "w") as arquivo:
        arquivo.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="dr" sheetId="1" r:id="rId1"/><sheet name="ESUN" sheetId="2" r:id="rId2"/></sheets></workbook>')
        arquivo.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        arquivo.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData><row r="169"><c r="A169"><v>167</v></c><c r="D169"><f t="shared" si="1"/><v>1.015794701</v></c></row></sheetData></worksheet>')
        esun = [2018.625038, 1860.152024, 1568.558433, 959.8728314, 238.7151843, 80.459523]
        linhas = ''.join(f'<row r="{b+2}"><c r="B{b+2}"><v>{b}</v></c><c r="C{b+2}"><v>{v}</v></c></row>' for b, v in enumerate(esun, 2))
        arquivo.writestr("xl/worksheets/sheet2.xml", f'<worksheet xmlns="{ns}"><sheetData>{linhas}</sheetData></worksheet>')


class SolarTest(unittest.TestCase):
    def test_mtl_tem_prioridade_sobre_planilha_e_registra_conferencia(self):
        with tempfile.TemporaryDirectory() as tmp:
            planilha = Path(tmp) / NOME_PLANILHA_SOLAR
            criar_planilha(planilha)
            mtl = {"IMAGE_ATTRIBUTES": {"DATE_ACQUIRED": "2025-06-16", "EARTH_SUN_DISTANCE": 1.0158233}}
            info = informacoes_solares(mtl, planilha)
            self.assertEqual(info["dia_ano"], 167)
            self.assertEqual(info["distancia_ua"], 1.0158233)
            self.assertEqual(info["distancia_planilha_ua"], 1.015794701)
            self.assertAlmostEqual(info["fator_inverso_quadrado"], 0.9690889909173899)
            self.assertIn("MTL", info["fonte"])
            pesos = info["pesos_esun_conferencia_b2_b7"]
            self.assertAlmostEqual(sum(pesos.values()), 1)
            self.assertNotIn("1", pesos)
            self.assertAlmostEqual(pesos["2"], 0.30010557, places=7)

    def test_descoberta_usa_planilha_quando_mtl_nao_tem_distancia(self):
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp)
            criar_planilha(entrada / NOME_PLANILHA_SOLAR)
            pasta = entrada / "cena"
            pasta.mkdir()
            (pasta / "Bandas_Empilhadas.tif").touch()
            mtl = {"IMAGE_ATTRIBUTES": {"DATE_ACQUIRED": "2025-06-16", "SPACECRAFT_ID": "LANDSAT_8"}}
            (pasta / "cena_MTL.json").write_text(json.dumps({"LANDSAT_METADATA_FILE": mtl}))
            cena, = descobrir_cenas(entrada)
            solar = cena["mtl"]["EVAPO_SOLAR"]
            self.assertIn("Planilha", solar["fonte"])
            self.assertEqual(solar["distancia_ua"], 1.015794701)
            self.assertAlmostEqual(fator_distancia_terra_sol(cena["mtl"]), 1 / 1.015794701**2)

    def test_ano_bissexto_e_inverso_quadrado_nas_estacoes(self):
        self.assertLess(distancia_terra_sol_data("2024-12-31"), 1)
        janeiro = {"IMAGE_ATTRIBUTES": {"DATE_ACQUIRED": "2025-01-04"}}
        julho = {"IMAGE_ATTRIBUTES": {"DATE_ACQUIRED": "2025-07-04"}}
        self.assertGreater(fator_distancia_terra_sol(janeiro), 1)
        self.assertLess(fator_distancia_terra_sol(julho), 1)
        with tempfile.TemporaryDirectory() as tmp:
            planilha = Path(tmp) / NOME_PLANILHA_SOLAR
            criar_planilha(planilha)
            info = informacoes_solares({"IMAGE_ATTRIBUTES": {"DATE_ACQUIRED": "2024-12-31"}}, planilha)
            self.assertEqual(info["dia_ano"], 366)
            self.assertIsNone(info["distancia_planilha_ua"])
            self.assertIn("Aproximação", info["fonte"])
            self.assertAlmostEqual(info["distancia_ua"], distancia_terra_sol_data("2024-12-31"))

    def test_distancia_nao_corrige_reflectancia_mtl_duas_vezes(self):
        mtl = {
            "IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30, "EARTH_SUN_DISTANCE": 1},
            "LEVEL1_RADIOMETRIC_RESCALING": {"REFLECTANCE_MULT_BAND_4": 0.00002, "REFLECTANCE_ADD_BAND_4": -0.1},
        }
        antes = converter_reflectancia(np.array([10000]), 4, mtl)
        curta_antes = calcular_radiacoes([0.75], mtl)["radiacao_curta_incidente"]
        mtl["IMAGE_ATTRIBUTES"]["EARTH_SUN_DISTANCE"] = 1.02
        np.testing.assert_array_equal(converter_reflectancia(np.array([10000]), 4, mtl), antes)
        curta_depois = calcular_radiacoes([0.75], mtl)["radiacao_curta_incidente"]
        np.testing.assert_allclose(curta_depois / curta_antes, [1 / 1.02**2], rtol=1e-6)

    def test_entradas_solares_invalidas_nao_usam_fallback_silencioso(self):
        for distancia in (0, -1, np.inf, np.nan, "abc"):
            with self.subTest(distancia=distancia), self.assertRaises(ValueError):
                fator_distancia_terra_sol({"IMAGE_ATTRIBUTES": {"EARTH_SUN_DISTANCE": distancia, "DATE_ACQUIRED": "2025-06-16"}})
        for data in ("2025-02-29", "2026-13-01", "abc"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                distancia_terra_sol_data(data)
        with self.assertRaises(ValueError):
            fator_distancia_terra_sol({"IMAGE_ATTRIBUTES": {}})


if __name__ == "__main__":
    unittest.main()
