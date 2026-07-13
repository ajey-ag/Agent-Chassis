from chassis.tools.registry import ToolRegistry


def make_registry():
    r = ToolRegistry()

    @r.register
    def greet(name: str, times: int = 1) -> str:
        """Greet someone by name.

        Args:
            name: Who to greet.
            times: How many times.
        """
        return " ".join([f"hi {name}"] * times)

    return r


def test_schema_from_hints_and_docstring():
    r = make_registry()
    spec = r.specs()[0]
    assert spec.name == "greet"
    assert spec.description == "Greet someone by name."
    assert spec.parameters["properties"]["name"] == {"type": "string", "description": "Who to greet."}
    assert spec.parameters["properties"]["times"]["type"] == "integer"
    assert spec.parameters["required"] == ["name"]


def test_call_and_string_coercion():
    r = make_registry()
    assert r.call("greet", {"name": "sam", "times": 2}) == "hi sam hi sam"


def test_unknown_tool_raises_keyerror():
    r = make_registry()
    try:
        r.call("nope", {})
        assert False
    except KeyError:
        pass
