"""Tests for prepare_code_for_result_capture function."""


from maya_mcp_server.maya_mcp_helper import prepare_code_for_result_capture


class TestPrepareCodeForResultCapture:
    """Tests for the prepare_code_for_result_capture function."""

    # =========================================================================
    # Cases that SHOULD be transformed
    # =========================================================================

    def test_simple_expression(self):
        """Simple expression should be transformed."""
        code = "1 + 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = 1 + 1\n"

    def test_variable_reference(self):
        """Variable reference expression should be transformed."""
        code = "x"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = x\n"

    def test_function_call(self):
        """Function call expression should be transformed."""
        code = "print('hello')"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = print('hello')\n"

    def test_method_call(self):
        """Method call expression should be transformed."""
        code = "cmds.ls()"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = cmds.ls()\n"

    def test_multiple_statements_expression_at_end(self):
        """Multiple statements with expression at end should transform only the last."""
        code = "x = 1\ny = 2\nx + y"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "x = 1\ny = 2\n_mcp_result = x + y\n"

    def test_list_literal(self):
        """List literal expression should be transformed."""
        code = "[1, 2, 3]"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = [1, 2, 3]\n"

    def test_dict_literal(self):
        """Dict literal expression should be transformed."""
        code = "{'a': 1, 'b': 2}"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = {'a': 1, 'b': 2}\n"

    def test_string_literal(self):
        """String literal expression should be transformed."""
        code = "'hello world'"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = 'hello world'\n"

    def test_multiline_expression(self):
        """Multi-line expression should be transformed."""
        code = "x = 1\n(1 +\n 2 +\n 3)"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "x = 1\n_mcp_result = 1 + 2 + 3\n"

    def test_multiline_function_call(self):
        """Multi-line function call should be transformed."""
        code = "some_function(\n    arg1,\n    arg2,\n    arg3\n)"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = some_function(arg1, arg2, arg3)\n"

    def test_lambda_expression(self):
        """Lambda expression should be transformed."""
        code = "lambda x: x + 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = lambda x: x + 1\n"

    def test_conditional_expression(self):
        """Conditional expression (ternary) should be transformed."""
        code = "1 if True else 2"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = 1 if True else 2\n"

    def test_list_comprehension(self):
        """List comprehension should be transformed."""
        code = "[x * 2 for x in range(10)]"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = [x * 2 for x in range(10)]\n"

    def test_generator_expression(self):
        """Generator expression should be transformed."""
        code = "(x * 2 for x in range(10))"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = (x * 2 for x in range(10))\n"

    def test_walrus_operator(self):
        """Named expression (walrus operator) should be transformed."""
        code = "(x := 5)"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = (x := 5)\n"

    def test_await_expression(self):
        """Await expression should be transformed (even if not in async context)."""
        code = "await some_coroutine()"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = await some_coroutine()\n"

    def test_yield_expression(self):
        """Yield expression should be transformed."""
        code = "yield 42"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = (yield 42)\n"

    # =========================================================================
    # Cases that should NOT be transformed
    # =========================================================================

    def test_assignment_not_transformed(self):
        """Assignment should NOT be transformed."""
        code = "x = 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_augmented_assignment_not_transformed(self):
        """Augmented assignment should NOT be transformed."""
        code = "x += 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_annotated_assignment_not_transformed(self):
        """Annotated assignment should NOT be transformed."""
        code = "x: int = 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_multiple_assignment_not_transformed(self):
        """Multiple assignment (tuple unpacking) should NOT be transformed."""
        code = "x, y = 1, 2"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_function_def_not_transformed(self):
        """Function definition should NOT be transformed."""
        code = "def foo():\n    return 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_async_function_def_not_transformed(self):
        """Async function definition should NOT be transformed."""
        code = "async def foo():\n    return 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_class_def_not_transformed(self):
        """Class definition should NOT be transformed."""
        code = "class Foo:\n    pass"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_for_loop_not_transformed(self):
        """For loop should NOT be transformed."""
        code = "for i in range(10):\n    print(i)"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_while_loop_not_transformed(self):
        """While loop should NOT be transformed."""
        code = "while True:\n    break"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_if_statement_not_transformed(self):
        """If statement should NOT be transformed."""
        code = "if True:\n    pass"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_try_statement_not_transformed(self):
        """Try statement should NOT be transformed."""
        code = "try:\n    pass\nexcept:\n    pass"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_with_statement_not_transformed(self):
        """With statement should NOT be transformed."""
        code = "with open('file') as f:\n    pass"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_import_not_transformed(self):
        """Import statement should NOT be transformed."""
        code = "import os"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_from_import_not_transformed(self):
        """From import statement should NOT be transformed."""
        code = "from os import path"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_assert_not_transformed(self):
        """Assert statement should NOT be transformed."""
        code = "assert True"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_raise_not_transformed(self):
        """Raise statement should NOT be transformed."""
        code = "raise ValueError('error')"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_pass_not_transformed(self):
        """Pass statement should NOT be transformed."""
        code = "pass"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_break_not_transformed(self):
        """Break statement should NOT be transformed (though invalid at top level)."""
        code = "break"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_continue_not_transformed(self):
        """Continue statement should NOT be transformed (though invalid at top level)."""
        code = "continue"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_return_not_transformed(self):
        """Return statement should NOT be transformed (though invalid at top level)."""
        code = "return 1"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_delete_not_transformed(self):
        """Delete statement should NOT be transformed."""
        code = "del x"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_global_not_transformed(self):
        """Global statement should NOT be transformed."""
        code = "global x"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_nonlocal_not_transformed(self):
        """Nonlocal statement should NOT be transformed (though invalid at top level)."""
        code = "nonlocal x"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    # =========================================================================
    # Edge cases
    # =========================================================================

    def test_empty_code(self):
        """Empty code should not be transformed."""
        code = ""
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == ""

    def test_whitespace_only(self):
        """Whitespace-only code should not be transformed."""
        code = "   \n\n   "
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == ""

    def test_comment_only(self):
        """Comment-only code should not be transformed."""
        code = "# just a comment"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_syntax_error(self):
        """Code with syntax error should return original."""
        code = "def foo(:"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is False
        assert result == code

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace should be stripped."""
        code = "1 + 1   \n\n"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = 1 + 1\n"

    def test_preserves_statements_before_expression(self):
        """Statements before the final expression should be preserved."""
        code = "import os\nx = 1\ny = 2\nx + y"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "import os\nx = 1\ny = 2\n_mcp_result = x + y\n"

    def test_semicolon_separated_statements(self):
        """Semicolon-separated statements - last expression captured."""
        code = "x = 1; 2"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "x = 1\n_mcp_result = 2\n"

    def test_expression_after_function_def(self):
        """Expression after function definition should be transformed."""
        code = "def foo():\n    return 1\nfoo()"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "def foo():\n    return 1\n_mcp_result = foo()\n"

    def test_expression_after_class_def(self):
        """Expression after class definition should be transformed."""
        code = "class Foo:\n    x = 1\nFoo.x"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "class Foo:\n    x = 1\n_mcp_result = Foo.x\n"

    def test_chained_attribute_access(self):
        """Chained attribute access should be transformed."""
        code = "obj.attr1.attr2.method()"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = obj.attr1.attr2.method()\n"

    def test_complex_expression(self):
        """Complex expression with operators should be transformed."""
        code = "(1 + 2) * 3 / 4 - 5 % 2"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = (1 + 2) * 3 / 4 - 5 % 2\n"

    def test_f_string(self):
        """F-string expression should be transformed."""
        code = 'f"Hello {name}"'
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = f'Hello {name}'\n"

    def test_comparison_expression(self):
        """Comparison expression should be transformed."""
        code = "1 < 2 < 3"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = 1 < 2 < 3\n"

    def test_boolean_expression(self):
        """Boolean expression should be transformed."""
        code = "True and False or True"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = True and False or True\n"

    def test_not_expression(self):
        """Not expression should be transformed."""
        code = "not True"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = not True\n"

    def test_subscript_expression(self):
        """Subscript expression should be transformed."""
        code = "my_list[0]"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = my_list[0]\n"

    def test_slice_expression(self):
        """Slice expression should be transformed."""
        code = "my_list[1:3]"
        result, transformed = prepare_code_for_result_capture(code)
        assert transformed is True
        assert result == "_mcp_result = my_list[1:3]\n"

    def test_custom_capture_variable(self):
        """Custom capture variable name should be used."""
        code = "1 + 1"
        result, transformed = prepare_code_for_result_capture(code, capture_variable="my_result")
        assert transformed is True
        assert result == "my_result = 1 + 1\n"


class TestResultExecution:
    """Test that transformed code actually executes correctly."""

    def test_transformed_code_executes(self):
        """Verify that transformed code captures the result correctly."""
        code = "1 + 1"
        transformed_code, _ = prepare_code_for_result_capture(code)

        namespace = {}
        exec(transformed_code, namespace)

        assert namespace["_mcp_result"] == 2

    def test_transformed_code_with_statements(self):
        """Verify transformed code with multiple statements works."""
        code = "x = 10\ny = 20\nx + y"
        transformed_code, _ = prepare_code_for_result_capture(code)

        namespace = {}
        exec(transformed_code, namespace)

        assert namespace["_mcp_result"] == 30
        assert namespace["x"] == 10
        assert namespace["y"] == 20

    def test_transformed_function_call_captures_return(self):
        """Verify that function return values are captured."""
        code = "def add(a, b):\n    return a + b\nadd(3, 4)"
        transformed_code, _ = prepare_code_for_result_capture(code)

        namespace = {}
        exec(transformed_code, namespace)

        assert namespace["_mcp_result"] == 7

    def test_list_comprehension_result(self):
        """Verify list comprehension result is captured."""
        code = "[x**2 for x in range(5)]"
        transformed_code, _ = prepare_code_for_result_capture(code)

        namespace = {}
        exec(transformed_code, namespace)

        assert namespace["_mcp_result"] == [0, 1, 4, 9, 16]

    def test_custom_capture_variable_execution(self):
        """Verify custom capture variable works in execution."""
        code = "2 * 3"
        transformed_code, _ = prepare_code_for_result_capture(code, capture_variable="result")

        namespace = {}
        exec(transformed_code, namespace)

        assert namespace["result"] == 6
        assert "_mcp_result" not in namespace
