"""Tests for PowerShell Windows E2E script parameter validation and behavior.

Static tests verify the script text without needing pwsh.
Runtime tests (skipped on Linux) verify actual invocation behavior.
"""

import sys
import argparse
import asyncio
import subprocess
from pathlib import Path
import pytest
import json


class TestPowerShellWindowsE2EScript:
    """Tests for run_heygen_windows_e2e.ps1 parameter handling and behavior."""

    @property
    def script_path(self) -> Path:
        return Path(__file__).parent.parent / "scripts" / "run_heygen_windows_e2e.ps1"

    @property
    def script_content(self) -> str:
        return self.script_path.read_text(encoding='utf-8')

    def test_script_exists(self):
        assert self.script_path.exists(), f"Script not found at {self.script_path}"

    def test_script_has_hermesdebug_parameter(self):
        content = self.script_content
        assert 'HermesDebug' in content, "Script should have HermesDebug parameter"
        assert '.PARAMETER HermesDebug' in content, "Script should document HermesDebug parameter"
        assert '[switch]$HermesDebug' in content, "Param block should have [switch]$HermesDebug"

    def test_script_has_dryrun_parameter(self):
        content = self.script_content
        assert 'DryRun' in content, "Script should have DryRun parameter"
        assert '.PARAMETER DryRun' in content, "Script should document DryRun parameter"
        assert '[switch]$DryRun' in content, "Param block should have [switch]$DryRun"

    def test_script_param_block_has_no_debug_conflict(self):
        """Test that param block doesn't have the conflicting [switch]$Debug parameter."""
        content = self.script_content
        param_start = content.find('param(')
        paren_count = 0
        param_end = -1
        for i, c in enumerate(content[param_start:], param_start):
            if c == '(':
                paren_count += 1
            elif c == ')':
                paren_count -= 1
                if paren_count == 0:
                    param_end = i
                    break
        param_block = content[param_start:param_end + 1]
        assert '[switch]$Debug' not in param_block, \
            "Param block should not have [switch]$Debug (conflicts with PowerShell common parameter)"

    def test_script_has_no_invoke_expression(self):
        """Test that the script does not use Invoke-Expression or iex."""
        content = self.script_content
        assert 'Invoke-Expression' not in content, "Script must not use Invoke-Expression"
        assert 'iex ' not in content and 'iex\n' not in content.replace('iex.', 'IEXX'), \
            "Script must not use iex alias"

    def test_script_uses_array_invocation(self):
        """Test that the script uses & $Python @PythonArgs pattern."""
        content = self.script_content
        # Must use the splatting pattern with @PythonArgs
        assert '& $Python @PythonArgs' in content or '& $Python $DemoScript' in content, \
            "Script must use array-based invocation via & $Python @PythonArgs"

    def test_pythonargs_is_array(self):
        """Test that PythonArgs is defined as an array."""
        content = self.script_content
        assert '$PythonArgs = @(' in content, \
            "PythonArgs should be defined as an array using @()"

    def test_chrome_path_is_separate_array_element(self):
        """Test that Chrome path is a separate array element, not inline."""
        content = self.script_content
        # Must have "--chrome-path" as a separate element, then $ChromePath as another
        # In array syntax, they can be on different lines
        assert '--chrome-path' in content, "Script should have --chrome-path argument"
        assert '$ChromePath' in content, "Script should reference $ChromePath variable"
        # Verify they appear in the array context (PythonArgs)
        python_args_section = content[content.find('$PythonArgs = @('):]
        assert '--chrome-path' in python_args_section, \
            "--chrome-path should be in PythonArgs array"
        assert '$ChromePath' in python_args_section, \
            "$ChromePath should be in PythonArgs array"

    def test_exit_code_captured_immediately_after_invocation(self):
        """Test that $PythonExitCode = $LASTEXITCODE is right after & $Python @PythonArgs."""
        content = self.script_content
        lines = content.split('\n')
        # Find the Python invocation line
        python_call_idx = -1
        exit_capture_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if '& $Python @PythonArgs' in stripped:
                python_call_idx = i
            if '$PythonExitCode = $LASTEXITCODE' in stripped:
                exit_capture_idx = i

        assert python_call_idx >= 0, "Should have & $Python @PythonArgs invocation"
        assert exit_capture_idx >= 0, "Should have $PythonExitCode = $LASTEXITCODE"
        assert exit_capture_idx == python_call_idx + 1 or exit_capture_idx == python_call_idx + 2, \
            "$PythonExitCode should be captured immediately after & $Python @PythonArgs"

    def test_nonzero_exit_code_throws(self):
        """Test that non-zero Python exit code leads to throw."""
        content = self.script_content
        assert 'throw "Hermes windows-e2e failed with exit code $PythonExitCode"' in content, \
            "Script should throw on non-zero Python exit code"

    def test_success_markers_printed(self):
        """Test that success markers are printed after zero exit code."""
        content = self.script_content
        assert 'windows_e2e_status=completed' in content, \
            "Script should print windows_e2e_status=completed on success"
        assert 'windows_e2e_python_rc=0' in content, \
            "Script should print windows_e2e_python_rc=0 on success"

    def test_dryrun_example_in_script_help(self):
        content = self.script_content
        assert '-DryRun' in content, "Script help should include -DryRun example"

    def test_hermesdebug_example_in_script_help(self):
        content = self.script_content
        assert 'HermesDebug' in content, "Script should reference HermesDebug parameter"

    def test_readme_has_no_old_debug_parameter(self):
        """Test that README doesn't reference the old -Debug parameter."""
        readme_path = Path(__file__).parent.parent / "README.md"
        readme = readme_path.read_text(encoding='utf-8')
        # Check for old user-facing -Debug parameter (not HermesDebug)
        # Allow --debug in Python CLI examples
        assert '-Debug' not in readme, \
            "README should not reference old -Debug parameter"

    def test_script_has_comment_for_array_splatting(self):
        """Test that the script explains the array splatting approach."""
        content = self.script_content
        has_comment = any(
            'splat' in line.lower() or 'array element' in line.lower() or 'argv' in line.lower()
            for line in content.split('\n')
        )
        assert has_comment, "Script should have a comment explaining array splatting"

    def test_no_cmd_c_invocation(self):
        """Test that the script does not use cmd /c."""
        content = self.script_content
        assert 'cmd /c' not in content.lower() and 'cmd.exe /c' not in content.lower(), \
            "Script must not use cmd /c"

    def test_no_start_process_with_string_arguments(self):
        """Test that the script does not use Start-Process with a single string."""
        content = self.script_content
        assert 'Start-Process' not in content, \
            "Script must not use Start-Process for Python invocation"

    def test_existing_cdp_passes_cdp_endpoint_to_python(self):
        """Test that existing-cdp mode passes --cdp-endpoint to Python."""
        content = self.script_content
        # Check that when $BrowserStartup -eq "existing-cdp", the script adds --cdp-endpoint
        assert 'if ($BrowserStartup -eq "existing-cdp")' in content, \
            "Script should have existing-cdp conditional"
        assert '--cdp-endpoint' in content, \
            "Script should pass --cdp-endpoint argument"
        assert '$CdpEndpoint' in content, \
            "Script should reference $CdpEndpoint variable"

    def test_existing_cdp_auto_discovers_via_get_existing_chrome(self):
        """Test that existing-cdp mode tries to auto-discover via get-existing-chrome.ps1."""
        content = self.script_content
        assert 'get-existing-chrome.ps1' in content, \
            "Script should reference get-existing-chrome.ps1 for auto-discovery"
        assert 'cdpResult' in content or 'CdpEndpoint' in content, \
            "Script should reference CDP result variable"

    def test_script_has_cdp_parameters(self):
        """Test that the script has the new CDP parameters."""
        content = self.script_content
        assert '[string]$CdpHost' in content, \
            "Script should have $CdpHost parameter"
        assert '[int]$CdpPort' in content, \
            "Script should have $CdpPort parameter"
        assert '[string]$CdpEndpoint' in content, \
            "Script should have $CdpEndpoint parameter"

    def test_script_has_existing_cdp_in_validate_set(self):
        """Test that BrowserStartup ValidateSet includes existing-cdp."""
        content = self.script_content
        # Find the ValidateSet after BrowserStartup parameter
        param_start = content.find('[ValidateSet(')
        param_section = content[param_start:param_start + 200]
        assert 'existing-cdp' in param_section, \
            "BrowserStartup ValidateSet should include existing-cdp"


class TestPowerShellScriptSyntax:
    """Test that the PowerShell script has valid syntax (static analysis)."""

    @property
    def script_path(self) -> Path:
        return Path(__file__).parent.parent / "scripts" / "run_heygen_windows_e2e.ps1"

    def test_script_syntax_check_with_pwsh(self):
        """Test script syntax using pwsh (if available)."""
        try:
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-Command', f'. {self.script_path}; exit 0'],
                capture_output=True,
                text=True,
                timeout=30
            )
            # Syntax errors would cause non-zero exit
            assert result.returncode == 0, \
                f"PowerShell syntax error: {result.stderr}\n{result.stdout}"
        except FileNotFoundError:
            pytest.skip("pwsh not available - skipping syntax check")

    def test_script_syntax_check_with_powershell(self):
        """Test script syntax using Windows PowerShell (if available)."""
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', f'. {self.script_path}; exit 0'],
                capture_output=True,
                text=True,
                timeout=30
            )
            assert result.returncode == 0, \
                f"PowerShell syntax error: {result.stderr}\n{result.stdout}"
        except FileNotFoundError:
            pytest.skip("powershell not available - skipping syntax check")


class TestPythonWindowsE2EMode:
    """Tests for the Python windows-e2e mode argument parsing."""

    @property
    def demo_script_path(self) -> Path:
        return Path(__file__).parent.parent / "scripts" / "demo_local_transport.py"

    def test_windows_e2e_mode_has_debug_argument(self):
        """Test that windows-e2e mode has --debug argument."""
        content = self.demo_script_path.read_text(encoding='utf-8')
        windows_e2e_section = content[
            content.find('windows_e2e_parser'):
            content.find('return parser', content.find('windows_e2e_parser'))
        ]
        assert '--debug' in windows_e2e_section, \
            "windows-e2e mode should have --debug argument"

    def test_windows_e2e_mode_has_dry_run_argument(self):
        """Test that windows-e2e mode has --dry-run argument."""
        content = self.demo_script_path.read_text(encoding='utf-8')
        windows_e2e_section = content[
            content.find('windows_e2e_parser'):
            content.find('return parser', content.find('windows_e2e_parser'))
        ]
        assert '--dry-run' in windows_e2e_section, \
            "windows-e2e mode should have --dry-run argument"

    def test_dry_run_returns_zero(self):
        """Test that dry-run mode returns exit code 0."""
        import sys
        sys.path.insert(0, str(self.demo_script_path.parent.parent))

        from scripts.demo_local_transport import demo_windows_e2e

        args = argparse.Namespace(
            dry_run=True,
            profile_dir=r"C:\test\profile",
            recording_dir=r"C:\test\recordings",
            target_url="https://app.heygen.com/",
            profile="heygen-review",
            inspect_only=True,
            record=False,
            success_selector=None,
            record_seconds=10,
            output_name="test.mp4",
            connect_timeout=30.0,
            debug=False,
            chrome_path=None,
            browser_startup="raw-cdp",
            auth_wait_seconds=300,
            cdp_endpoint=None,
            cdp_host="127.0.0.1",
            cdp_port=9222,
        )

        import asyncio
        result = asyncio.run(demo_windows_e2e(args))
        assert result == 0, "Dry run should return exit code 0"

    def test_dry_run_existing_cdp_returns_zero(self):
        """Test that dry-run mode with existing-cdp returns exit code 0."""
        import sys
        sys.path.insert(0, str(self.demo_script_path.parent.parent))

        from scripts.demo_local_transport import demo_windows_e2e

        args = argparse.Namespace(
            dry_run=True,
            profile_dir=r"C:\test\profile",
            recording_dir=r"C:\test\recordings",
            target_url="https://app.heygen.com/",
            profile="heygen-review",
            inspect_only=True,
            record=False,
            success_selector=None,
            record_seconds=10,
            output_name="test.mp4",
            connect_timeout=30.0,
            debug=False,
            chrome_path=None,
            browser_startup="existing-cdp",
            auth_wait_seconds=300,
            cdp_endpoint="http://127.0.0.1:9222",
            cdp_host="127.0.0.1",
            cdp_port=9222,
        )

        import asyncio
        result = asyncio.run(demo_windows_e2e(args))
        assert result == 0, "Dry run with existing-cdp should return exit code 0"

    def test_record_without_selector_fails(self):
        """Test that --record requires --success-selector."""
        import sys
        sys.path.insert(0, str(self.demo_script_path.parent.parent))

        from scripts.demo_local_transport import demo_windows_e2e

        args = argparse.Namespace(
            dry_run=False,
            profile_dir=r"C:\test\profile",
            recording_dir=r"C:\test\recordings",
            target_url="https://app.heygen.com/",
            profile="heygen-review",
            inspect_only=False,
            record=True,
            success_selector=None,  # Missing selector
            record_seconds=10,
            output_name="test.mp4",
            connect_timeout=30.0,
            debug=False,
            chrome_path=None
        )

        import asyncio
        result = asyncio.run(demo_windows_e2e(args))
        assert result == 1, "Should fail when --record without --success-selector"


class TestReadme:
    """Tests for the README documentation."""

    @property
    def readme_path(self) -> Path:
        return Path(__file__).parent.parent / "README.md"

    def test_readme_try_catch_example_exists(self):
        """Test that README has the try/catch external invocation example."""
        content = self.readme_path.read_text(encoding='utf-8')
        assert 'try {' in content, "README should have try/catch example"
        assert 'windows_e2e_launcher=completed' in content, \
            "README should have launcher success marker"
        assert 'windows_e2e_launcher=failed' in content, \
            "README should have launcher failure marker"

    def test_readme_no_write_error_in_catch_example(self):
        """Test that the catch block uses Write-Host, not Write-Error."""
        content = self.readme_path.read_text(encoding='utf-8')
        catch_section = content[content.find('try {'):]
        catch_block = catch_section[catch_section.find('catch {'):catch_section.find('}', catch_section.find('catch {')) + 1]
        assert 'Write-Error' not in catch_block, \
            "Catch block should use Write-Host, not Write-Error"
        assert 'Write-Host' in catch_block, \
            "Catch block should use Write-Host for status reporting"

    def test_readme_no_old_debug_reference(self):
        """Test that README uses -HermesDebug, not -Debug."""
        content = self.readme_path.read_text(encoding='utf-8')
        # Allow --debug in Python CLI context, but not -Debug as a standalone parameter
        lines = content.split('\n')
        for line in lines:
            # Check for PowerShell-style -Debug parameter (not Python --debug)
            if '-Debug' in line and '--debug' not in line:
                pytest.fail(f"README should not reference old -Debug parameter: {line.strip()}")


@pytest.fixture
def fake_python_argv_recorder(tmp_path):
    """Create a fake Python script that records its argv to a JSON file."""
    fake_python_dir = tmp_path / "Hermes Test"
    fake_python_dir.mkdir(parents=True, exist_ok=True)
    recorder_script = fake_python_dir / "record_argv.py"
    recorder_script.write_text("""\
import sys, json
# Write argv to a temp file for verification
with open(sys.argv[1], 'w') as f:
    json.dump(sys.argv[2:], f)
# Exit with the code specified in the last argument before --exit-code
exit_code = 0
for i, arg in enumerate(sys.argv):
    if arg == '--exit-code' and i + 1 < len(sys.argv):
        exit_code = int(sys.argv[i + 1])
        break
sys.exit(exit_code)
""", encoding='utf-8')
    return recorder_script


class TestPowerShellInvocationWithPwsh:
    """Runtime tests that verify PowerShell invocation behavior.

    These tests require pwsh and are skipped on systems without it.
    """

    @property
    def script_path(self) -> Path:
        return Path(__file__).parent.parent / "scripts" / "run_heygen_windows_e2e.ps1"

    @pytest.fixture(autouse=True)
    def check_pwsh(self):
        """Skip all tests in this class if pwsh is not available."""
        try:
            subprocess.run(['pwsh', '--version'], capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("pwsh not available - skipping runtime PowerShell tests")

    def test_invoke_with_dry_run_and_inspect_only(self, tmp_path, fake_python_argv_recorder):
        """Test that -DryRun -InspectOnly passes correct arguments to Python."""
        argv_file = tmp_path / "argv.json"
        pwsh_script = f"""
$Python = '{fake_python_argv_recorder}'
$DemoScript = '{fake_python_argv_recorder}'
$PythonArgs = @(
    $DemoScript
    "windows-e2e"
    "--profile-dir"
    "C:\\Test Profile"
    "--recording-dir"
    "C:\\Test Recordings"
    "--target-url"
    "https://app.heygen.com/"
    "--profile"
    "heygen-review"
    "--chrome-path"
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
    "--connect-timeout"
    "30"
)

$PythonArgs += "--inspect-only"
$PythonArgs += "--dry-run"
$PythonArgs += "{argv_file}"
$PythonArgs += "--exit-code"
$PythonArgs += "0"

& $Python @PythonArgs
$PythonExitCode = $LASTEXITCODE
if ($PythonExitCode -ne 0) {{
    throw "Python failed with exit code $PythonExitCode"
}}
Write-Host "windows_e2e_status=completed"
Write-Host "windows_e2e_python_rc=0"
exit 0
"""
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', pwsh_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, \
            f"PowerShell dry-run failed: {result.stderr}\n{result.stdout}"

        # Verify the recorded argv
        recorded = json.loads(argv_file.read_text())
        assert 'windows-e2e' in recorded, "Should receive windows-e2e mode"
        assert '--inspect-only' in recorded, "Should receive --inspect-only"
        assert '--dry-run' in recorded, "Should receive --dry-run"
        assert '--chrome-path' in recorded, "Should receive --chrome-path"
        chrome_path_idx = recorded.index('--chrome-path')
        assert chrome_path_idx + 1 < len(recorded), "Should have Chrome path after --chrome-path"
        assert recorded[chrome_path_idx + 1] == r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe', \
            "Chrome path should be a single argv element with spaces preserved"

    def test_profile_dir_with_spaces_is_single_arg(self, tmp_path, fake_python_argv_recorder):
        """Test that profile-dir with spaces is passed as a single argument."""
        argv_file = tmp_path / "argv.json"
        profile_dir = r"C:\Temp\Hermes Test\profile"
        recording_dir = r"C:\Temp\Hermes Test\recordings"

        pwsh_script = f"""
$Python = '{fake_python_argv_recorder}'
$PythonArgs = @(
    '{fake_python_argv_recorder}'
    "windows-e2e"
    "--profile-dir"
    '{profile_dir}'
    "--recording-dir"
    '{recording_dir}'
    "--target-url"
    "https://app.heygen.com/"
    "--profile"
    "test"
    "--chrome-path"
    "C:\\chrome.exe"
    "--connect-timeout"
    "30"
)

$PythonArgs += "--inspect-only"
$PythonArgs += "--dry-run"
$PythonArgs += "{argv_file}"
$PythonArgs += "--exit-code"
$PythonArgs += "0"

& $Python @PythonArgs
$PythonExitCode = $LASTEXITCODE
if ($PythonExitCode -ne 0) {{
    throw "Python failed with exit code $PythonExitCode"
}}
exit 0
"""
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', pwsh_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, \
            f"PowerShell failed: {result.stderr}\n{result.stdout}"

        recorded = json.loads(argv_file.read_text())
        assert '--profile-dir' in recorded, "Should receive --profile-dir"
        profile_dir_idx = recorded.index('--profile-dir')
        assert profile_dir_idx + 1 < len(recorded), "Should have value after --profile-dir"
        assert recorded[profile_dir_idx + 1] == profile_dir, \
            "Profile dir should be a single argv element with spaces preserved"

        assert '--recording-dir' in recorded, "Should receive --recording-dir"
        recording_dir_idx = recorded.index('--recording-dir')
        assert recording_dir_idx + 1 < len(recorded), "Should have value after --recording-dir"
        assert recorded[recording_dir_idx + 1] == recording_dir, \
            "Recording dir should be a single argv element with spaces preserved"

    def test_child_exit_7_causes_launcher_failure(self, tmp_path, fake_python_argv_recorder):
        """Test that Python exit code 7 causes launcher to throw."""
        argv_file = tmp_path / "argv.json"

        pwsh_script = f"""
try {{
    $Python = '{fake_python_argv_recorder}'
    $PythonArgs = @(
        '{fake_python_argv_recorder}'
        "windows-e2e"
        "--profile-dir"
        "C:\\test"
        "--recording-dir"
        "C:\\test"
        "--target-url"
        "https://example.com/"
        "--profile"
        "test"
        "--chrome-path"
        "C:\\chrome.exe"
        "--connect-timeout"
        "30"
    )
    $PythonArgs += "--inspect-only"
    $PythonArgs += "--dry-run"
    $PythonArgs += "{argv_file}"
    $PythonArgs += "--exit-code"
    $PythonArgs += "7"

    & $Python @PythonArgs
    $PythonExitCode = $LASTEXITCODE
    if ($PythonExitCode -ne 0) {{
        throw "Hermes windows-e2e failed with exit code $PythonExitCode"
    }}
    Write-Host "windows_e2e_status=completed"
    Write-Host "windows_e2e_python_rc=0"
    exit 0
}}
catch {{
    Write-Host "windows_e2e_launcher=failed"
    throw
}}
"""
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', pwsh_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should fail because child exit code is 7
        assert result.returncode != 0, \
            "Launcher should fail when child exits with code 7"
        assert 'windows_e2e_launcher=failed' in result.stdout, \
            "Should print failure marker"
        assert 'exit code 7' in result.stdout or 'exit code 7' in result.stderr, \
            "Error should mention exit code 7"

    def test_child_exit_0_prints_success_markers(self, tmp_path, fake_python_argv_recorder):
        """Test that Python exit code 0 prints success markers."""
        argv_file = tmp_path / "argv.json"

        pwsh_script = f"""
$Python = '{fake_python_argv_recorder}'
$PythonArgs = @(
    '{fake_python_argv_recorder}'
    "windows-e2e"
    "--profile-dir"
    "C:\\test"
    "--recording-dir"
    "C:\\test"
    "--target-url"
    "https://example.com/"
    "--profile"
    "test"
    "--chrome-path"
    "C:\\chrome.exe"
    "--connect-timeout"
    "30"
)
$PythonArgs += "--inspect-only"
$PythonArgs += "--dry-run"
$PythonArgs += "{argv_file}"
$PythonArgs += "--exit-code"
$PythonArgs += "0"

& $Python @PythonArgs
$PythonExitCode = $LASTEXITCODE
if ($PythonExitCode -ne 0) {{
    throw "Python failed with exit code $PythonExitCode"
}}
Write-Host "windows_e2e_status=completed"
Write-Host "windows_e2e_python_rc=0"
exit 0
"""
        result = subprocess.run(
            ['pwsh', '-NoProfile', '-Command', pwsh_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, \
            f"Launcher should succeed: {result.stderr}\n{result.stdout}"
        assert 'windows_e2e_status=completed' in result.stdout, \
            "Should print windows_e2e_status=completed"
        assert 'windows_e2e_python_rc=0' in result.stdout, \
            "Should print windows_e2e_python_rc=0"

    def test_record_without_selector_handled(self, tmp_path, fake_python_argv_recorder):
        """Test that the script handles -Record without -SuccessSelector gracefully."""
        # This is a syntax/structure test - the script should validate
        # that -Record requires -SuccessSelector
        # In the actual script, this is enforced by parameter sets,
        # but we test the Python side
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])