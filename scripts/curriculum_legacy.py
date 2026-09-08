"""Reviewed repairs for immutable, malformed historical undergraduate records.

Repeated empty complex-analysis topics name the same entry. Repeated Hilbert
space labels instead refer to DIFFERENT examples, identified by their reference
and neighbors; retain each. The l^2 / L^2 names agree with upstream's later fix
in mathlib4 63ca896d7c056a1cb9d9abd5f41afb4c19a5f32b.
Unknown blobs still use the strict parser. These are not general duplicate-key
exceptions and do not mask future upstream errors.
"""

from __future__ import annotations

import hashlib

import yaml

from coverage_model import DataError, load_yaml

REVIEWED_BLOBS = frozenset({
    "037346590d914ab6cb11000418a26fd6e4af7236",
    "03f1410571e8c1fc0fa6fd0df107db2affc22bf9",
    "04bd976270e8fa38a02a67fdb52e90d41bd8c636",
    "075c1b786017983677058ebd65884f5bfc04a66b",
    "12f61a657259fdbd93df7adee168d6c425f2cf4c",
    "134f166f3b27632ee5c0e8c17879d0034f2a1560",
    "1432c5fd43159efe87a4d3041876ddeabc234666",
    "18d92c12e930f2e541aa478cae14cad4a338254e",
    "1bc5db30ac1e4a4a13977dc5b2f06025fec0a48a",
    "24bfa7f6de38faa40615919883fa222a5dca1ee8",
    "27cbaf9294b163a34019834a74ab48d181fe1f20",
    "2aa4442294e9ae8d16cd9d49e55c616b8044e3f0",
    "2b095aa696327fba980c952da1d6713fc8cf5ad8",
    "2b45ce944747e3c2c0509889c43ca619943f867a",
    "2bc3d661f34fffa1772c8b11d0d7c134f380194f",
    "3008a9394dd9730447ed3a6c7468601ba90d19fd",
    "33ad946cb54f63532016cb1a0478b5c00cf44f24",
    "3810cf2622351d7c8bc9f51da624443e13d06b6b",
    "3b3c790f4345bc173184e86ba62ec1ec93e5002c",
    "3ff489534b0ec0104b51b2395f279ded95b6842d",
    "409549142f62e39be1b26b89105b98cd9f2f397a",
    "450ce4b9a2365c392f39aebe72ebeecd64bcb51e",
    "458480a23bc1523ed1ff9e08b18713c005a007f8",
    "4742407443a40fb5c4dc0a84e3d83c876b730423",
    "475c76a60f0213339be5ccfc22e3c2bbd2925952",
    "4b39ab97ab21b5e159f731ba99900e5c591d1edc",
    "4c527cb63e9bd4323b2d18ef28f053c9e6bf2991",
    "4ce956c384017888fc00e36f709813dae3ff4a54",
    "4d8c3000d566935b598d85268430ee86af7979d9",
    "4df6c8fac7a734e33761514886f1bf6e45427571",
    "4f27043f36f9e4a8e13bd34195bb7067d5425c9c",
    "510b37c89d50679bd5c2b68057465d5998592436",
    "51bf33e5f7f091e3ffa9d03cfab5038a51b86abe",
    "525815c173d7cab2a50280565da2d1321464af74",
    "53f3c4f33e14158c1b54e2a44e9d2a55fc3eaebc",
    "581a655acf7dda88c21746c3664b99c255f88898",
    "58f27afa5e75718f4e24c4a39cffd4a8c518f67f",
    "5a4fcb6bcd3deb1f4b76b4f5cfb16713a8640255",
    "5c8a184edd4b4c98290417c9c3108ea8306200e1",
    "67bd2157248a249ba25d8421b7db2d9bc62c2c05",
    "6803a9217fd616e5eaa94f855bc7fe35a8670ba9",
    "6a2b40b3051f5b5766fd74de1a688ffcae3daf90",
    "6a6e11e3613bf483dd6b78fa1b70eb77f0f55665",
    "6f6f7c711309a82cde80218f15895a8f8fca0c2e",
    "7bc41ef6bd4b4693faad1ca2500543f9f85592ab",
    "810e4356efa7cf82622d31e1e1a22619e1abcea5",
    "856f6d44c5aa09941b606ea5e6619618e375a61b",
    "8cb83ed8e17d120559721d93fd74863f4ae3873b",
    "8e38a2ece7e0be47ae5b0006d8c1f359d1963851",
    "9c0f4d78a13bcaee0fcb733f089a935a3198c1bc",
    "9c3c4ffe3d3fce9e0a0fb5ed7f451e50d4ad21c9",
    "b3fadc2ee96c2977b63110a7794f18d710bdce3b",
    "b5e509f9871ad141aedee1d5910679b8d9167416",
    "b775dd5c45787fc98795bd583661c31cff6e77e5",
    "b83c8340931a68a5f04b78219ccad95df80a7121",
    "b9fe40e3e405abdc8e1194b86608c2f708293bb9",
    "bc32e8f2b0b5166107447bbae921ac88e378db7c",
    "bc923730f01af479d95095bb81ca7670f9684bcf",
    "c06e0704ee45c6cc2f816b2ba3c900d6cc8bddaa",
    "c219962bbf266eb3af9995f800931276fd19a4eb",
    "c78aec4a3edbdd48421578d4ea4a197020154e82",
    "c80477a9d3728df77b2f4835eb8d0dd70cb5099c",
    "c82b8a60785fe712e214fa13f934d3709d222f22",
    "c984b13916c83e2d4be66d50e37db4f47e8d8110",
    "cb9ea6a1003475d9aca5e14a17e1d7d133e73125",
    "cf64008df7773221f94aeb4daff98f7a6a967614",
    "d65baef8bfd246e7f022187d4cc637c98165061c",
    "d7c5dee0a7c3b1926f5fb1dea618ccc69860c4ac",
    "d82118474c79b3536b45de7fad91c505144a752f",
    "dbf5b33bf7b4ad66d867947b554954b1ea24d262",
    "e07effb6ede1cddc40b50a82f917fa50ecaae755",
    "e37577deec32e5337fb4dc2fc57a5630ecfa3cf0",
    "e5175a4c9d39de07157749b2cfb03c13e12981d7",
    "e5e7aef2c4559c867459bc4118fdb71a6fb88675",
    "e96d8a1997e341a4b96ee08bc3d819bc14e35044",
    "eccd67d980bec8f02918d992d51ea0b218153587",
    "f0d85a925e463d118585bd39b0f72225e1ee0c7c",
    "f410a270b228b340209d620dccf5051e1c7ac932",
})

COMPLETENESS_LABELS = {
    "lp.complete_space": "completeness of $l^2$",
    "lp.instCompleteSpace": "completeness of $l^2$",
    "measure_theory.Lp.complete_space": "completeness of $L^2$",
    "MeasureTheory.Lp.instCompleteSpace": "completeness of $L^2$",
    "span_fourier_Lp_closure_eq_top": "completeness of the trigonometric Hilbert basis",
}


def blob_hash(content: str) -> str:
    raw = content.encode("utf-8")
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def _repair(node: yaml.Node, notes: dict, path: tuple[str, ...] = ()) -> None:
    if not isinstance(node, yaml.MappingNode):
        return
    seen = {}
    children = []
    for key, value in node.value:
        label = key.value
        if path == ("Topology", "Hilbert spaces") and label == "its completeness":
            if not isinstance(value, yaml.ScalarNode) or value.value not in COMPLETENESS_LABELS:
                raise DataError("Unreviewed historical Hilbert-space reference")
            label = COMPLETENESS_LABELS[value.value]
            key = yaml.ScalarNode("tag:yaml.org,2002:str", label)
            notes[path + (label,)] = (
                "Reviewed historical label repair: 'its completeness' referred to this "
                "particular Hilbert-space example. Distinct examples are counted separately."
            )
        if (
            path == ("Single Variable Complex Analysis", "Functions on one complex variable")
            and label in ("Cauchy formulas", "analyticity of a holomorphic function")
            and label in seen
        ):
            if value.tag != "tag:yaml.org,2002:null" or seen[label].tag != value.tag:
                raise DataError("Unreviewed repeated complex-analysis reference")
            notes[path + (label,)] = "Reviewed historical repair: identical repeated empty label counted once."
            continue
        seen[label] = value
        _repair(value, notes, path + (label,))
        children.append((key, value))
    node.value = children


def load_curriculum(content: str) -> tuple[dict, dict]:
    if blob_hash(content) not in REVIEWED_BLOBS:
        return load_yaml(content), {}
    notes: dict[tuple[str, ...], str] = {}
    node = yaml.compose(content, Loader=yaml.SafeLoader)
    _repair(node, notes)
    if not notes:
        raise DataError("Reviewed legacy blob no longer matches its repair")
    return load_yaml(yaml.serialize(node)), notes
