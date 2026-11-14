"""Confere o catalogo sem banco: ids unicos, todas as dimensoes cobertas, decisoes justificadas."""
from src.qualidade.catalogo import construir_catalogo
from src.qualidade.regras import DIMENSOES


def test_catalogo():
    cat = construir_catalogo("campo_real_energia")
    ids = [r.id for r in cat]
    assert len(ids) == len(set(ids))
    assert {r.dimensao for r in cat} == set(DIMENSOES)
    assert all(len(r.justificativa) > 30 and callable(r.medir) for r in cat)


if __name__ == "__main__":
    test_catalogo()
    print("ok test_catalogo")
