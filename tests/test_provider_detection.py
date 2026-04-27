import pushkey


def test_detect_provider_by_name_pattern():
    assert pushkey.detect_provider("OPENAI_API_KEY") == "OpenAI"
    assert pushkey.detect_provider("ANTHROPIC_API_KEY") == "Anthropic"
    assert pushkey.detect_provider("OANDA_TOKEN") == "OANDA"


def test_detect_provider_by_value_prefix():
    assert pushkey.detect_provider("ANY_KEY", "sk-test123") == "OpenAI"
    assert pushkey.detect_provider("ANY_KEY", "sk-ant-test123") == "Anthropic"
    assert pushkey.detect_provider("ANY_KEY", "AKIA1234567890TEST") == "AWS"


def test_detect_provider_unknown():
    assert pushkey.detect_provider("SOME_RANDOM_KEY", "xyz") is None

