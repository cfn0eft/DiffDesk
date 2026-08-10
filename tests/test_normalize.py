from diffdesk.core import DiffOptions, make_normalizer, values_equal


def test_trim_includes_fullwidth_space():
    n = make_normalizer(DiffOptions(trim=True, normalize_width=False))
    assert n("　山田 太郎　") == "山田 太郎"


def test_nfkc_width():
    n = make_normalizer(DiffOptions())
    assert n("ＡＢＣ１２３") == "ABC123"
    assert n("ｶﾀｶﾅ") == "カタカナ"
    assert n("㈱テスト") == "(株)テスト"


def test_nfkc_then_retrim():
    # 全角空白はNFKCで半角空白になるため再トリムが必要
    n = make_normalizer(DiffOptions())
    assert n("山田　") == "山田"


def test_casefold():
    n = make_normalizer(DiffOptions(ignore_case=True))
    assert n("Abc") == n("ABC")


def test_no_options_identity():
    n = make_normalizer(DiffOptions(trim=False, normalize_width=False))
    assert n(" ＡＢ ") == " ＡＢ "


def test_numeric_tolerance():
    n = make_normalizer(DiffOptions())
    assert values_equal("100.0", "100", n, numeric_tolerance=0.0)
    assert values_equal("100.05", "100", n, numeric_tolerance=0.1)
    assert not values_equal("101", "100", n, numeric_tolerance=0.5)
    # 数値でない場合は文字列比較にフォールバック
    assert not values_equal("1,000", "1000", n, numeric_tolerance=0.1)
    assert values_equal("abc", "abc", n, numeric_tolerance=0.1)
