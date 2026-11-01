import base64
import subprocess
import unittest
from unittest import mock
from xml.dom import minidom

import winprep

BATTLENET = """# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.28.0.schema.json

PackageIdentifier: Blizzard.BattleNet
PackageVersion: 2.0.0.4232
InstallerType: exe
Scope: machine
Installers:
- InstallerUrl: https://downloader.battle.net/download/getInstaller?os=win&installer=Battle.net-Setup.exe
  Architecture: x86
  InstallerSha256: F4643A2086C0CECB1AB68CC601BF38C1A0A6F7EF5914AD03375CC9449385BEC6
  InstallerSwitches:
    Custom: --lang=enUS
    InstallLocation: --installpath="<INSTALLPATH>"
  InstallLocationRequired: true
InstallationMetadata:
  DefaultInstallLocation: '%PROGRAMFILES(X86)%\\Battle.net'
ManifestType: installer
"""

VSCODE = """PackageIdentifier: Microsoft.VisualStudioCode
InstallerType: inno
InstallerSwitches:
  Custom: /mergetasks=!runcode
Commands:
- code
Installers:
- Architecture: x64
  Scope: user
  InstallerUrl: https://example.com/VSCodeUserSetup-x64.exe
  InstallerSha256: AA
- Architecture: x64
  Scope: machine
  InstallerUrl: https://example.com/VSCodeSetup-x64.exe
  InstallerSha256: BB
- Architecture: arm64
  Scope: machine
  InstallerUrl: https://example.com/VSCodeSetup-arm64.exe
  InstallerSha256: CC
"""

EA = """InstallerType: burn
InstallerSwitches:
  Silent: /passive /norestart
  Custom: /norestart
Installers:
- Architecture: x64
  InstallerUrl: https://example.com/EAappInstaller.exe
  InstallerSha256: DD
"""

GENERATED = """<?xml version="1.0" encoding="utf-8"?>\r
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">\r
\t<!--https://schneegans.de/windows/unattend-generator/?AccountPassword0=XPLACEHOLDERX&ProductKey=VK7JG-NPHTM-C97JM-9MPGT-3V66T-->\r
\t<settings pass="windowsPE"><component name="Microsoft-Windows-Setup"><UserData><ProductKey><Key>VK7JG-NPHTM-C97JM-9MPGT-3V66T</Key></ProductKey></UserData></component></settings>\r
\t<settings pass="specialize"><component name="Microsoft-Windows-Shell-Setup"><ProductKey>VK7JG-NPHTM-C97JM-9MPGT-3V66T</ProductKey></component></settings>\r
\t<settings pass="oobeSystem"><component name="Microsoft-Windows-Shell-Setup">\r
\t\t<UserAccounts><LocalAccounts><LocalAccount wcm:action="add"><Password><Value>{pw}</Value></Password></LocalAccount></LocalAccounts></UserAccounts>\r
\t\t<AutoLogon><Password><Value>{pw}</Value></Password></AutoLogon>\r
\t\t<OOBE><HideOnlineAccountScreens>false</HideOnlineAccountScreens></OOBE>\r
\t\t<FirstLogonCommands>\r
\t\t\t<SynchronousCommand wcm:action="add"><Order>1</Order><CommandLine>FirstLogon.ps1</CommandLine></SynchronousCommand>\r
\t\t</FirstLogonCommands>\r
\t</component></settings>\r
</unattend>\r
""".replace("{pw}", winprep.obscure(winprep.PW_PLACEHOLDER))


class Yaml(unittest.TestCase):
    def test_winget_installer_manifest(self):
        m = winprep.yaml_load(BATTLENET)
        self.assertEqual(m["PackageVersion"], "2.0.0.4232")
        inst = m["Installers"][0]
        self.assertTrue(inst["InstallerUrl"].endswith("installer=Battle.net-Setup.exe"))
        self.assertEqual(inst["InstallerSwitches"]["InstallLocation"], '--installpath="<INSTALLPATH>"')
        self.assertEqual(m["InstallationMetadata"]["DefaultInstallLocation"], "%PROGRAMFILES(X86)%\\Battle.net")

    def test_scalar_lists(self):
        self.assertEqual(winprep.yaml_load(VSCODE)["Commands"], ["code"])

    def test_versions_sort_numerically(self):
        self.assertEqual(max(["2.9.0", "2.10.1", "2.10.0"], key=winprep.vkey), "2.10.1")


class Installers(unittest.TestCase):
    def test_prefers_machine_x64_and_inherits_switches(self):
        inst = winprep.pick_installer(winprep.yaml_load(VSCODE))
        self.assertEqual(inst["InstallerUrl"], "https://example.com/VSCodeSetup-x64.exe")
        self.assertEqual(winprep.silent_args(inst),
                         ("inno", "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /mergetasks=!runcode"))

    def test_falls_back_to_x86_and_fills_install_location(self):
        inst = winprep.pick_installer(winprep.yaml_load(BATTLENET))
        self.assertEqual(winprep.silent_args(inst),
                         ("exe", '--lang=enUS --installpath="%PROGRAMFILES(X86)%\\Battle.net"'))

    def test_preferred_type_and_fallback_location(self):
        man = {"InstallLocationRequired": "true", "InstallerSwitches": {"InstallLocation": '-o"<INSTALLPATH>"'},
               "Installers": [{"Architecture": "x64", "InstallerType": "msix", "InstallerUrl": "a"},
                              {"Architecture": "x64", "InstallerType": "exe", "InstallerUrl": "b"}]}
        self.assertEqual(winprep.pick_installer(man)["InstallerUrl"], "a")
        inst = winprep.pick_installer(man, prefer="exe")
        self.assertEqual(inst["InstallerUrl"], "b")
        self.assertEqual(winprep.silent_args(inst, r"%LOCALAPPDATA%\T"), ("exe", r'-o"%LOCALAPPDATA%\T"'))
        self.assertEqual(winprep.pick_installer(man, prefer="wix")["InstallerUrl"], "a")  # not offered: ignored

    def test_custom_switches_not_duplicated(self):
        inst = winprep.pick_installer(winprep.yaml_load(EA))
        self.assertEqual(winprep.silent_args(inst), ("burn", "/passive /norestart"))


class AnswerFile(unittest.TestCase):
    def test_obscured_password_matches_windows_format(self):
        self.assertEqual(base64.b64decode(winprep.obscure("pw")).decode("utf-16-le"), "pwPassword")

    def test_secrets_substituted_locally(self):
        out = winprep.finalize_answer(GENERATED, "s3cret", "ABCDE-FGHIJ-KLMNO-PQRST-UVWXY",
                                      winprep.GENERIC_KEYS["pro"])
        minidom.parseString(out.encode("utf-8"))
        self.assertEqual(out.count(winprep.obscure("s3cret")), 2)
        self.assertNotIn(winprep.PW_PLACEHOLDER, out)
        self.assertEqual(out.count("<Key>ABCDE-FGHIJ-KLMNO-PQRST-UVWXY</Key>"), 1)
        self.assertEqual(out.count("<ProductKey>ABCDE-FGHIJ-KLMNO-PQRST-UVWXY</ProductKey>"), 1)
        self.assertNotIn("ABCDE-FGHIJ", out.split("-->")[0])  # never in the source-URL comment
        self.assertIn("<HideOnlineAccountScreens>true</HideOnlineAccountScreens>", out)
        self.assertNotIn("\r", out)

    def test_first_logon_command_appended_in_order(self):
        out = winprep.finalize_answer(GENERATED, "", None, winprep.GENERIC_KEYS["pro"])
        doc = minidom.parseString(out.encode("utf-8"))
        cmds = doc.getElementsByTagName("SynchronousCommand")
        self.assertEqual([c.getElementsByTagName("Order")[0].firstChild.data for c in cmds], ["1", "2"])
        self.assertIn("install-apps.ps1", cmds[1].getElementsByTagName("CommandLine")[0].firstChild.data)
        self.assertIn("<Key>VK7JG-NPHTM-C97JM-9MPGT-3V66T</Key>", out)  # no key given: generic stays

    def test_rejects_malformed_key(self):
        with self.assertRaises(ValueError):
            winprep.finalize_answer(GENERATED, "", "not-a-key", winprep.GENERIC_KEYS["pro"])

    def test_generator_params(self):
        conf = dict(winprep.DEFAULTS, INPUT="en-US:00000409 bg-BG:00040402", REMOVE="Copilot Recall",
                    COMPUTER_NAME="PC", GENERATOR_EXTRA="ColorMode=Custom SystemColorTheme=Dark")
        p = winprep.generator_params(conf)
        self.assertEqual((p["Locale2"], p["Keyboard2"], p["UseKeyboard2"]), ("bg-BG", "00040402", "true"))
        self.assertEqual((p["RemoveCopilot"], p["RemoveRecall"]), ("true", "true"))
        self.assertEqual(p["AccountPassword0"], winprep.PW_PLACEHOLDER)
        self.assertEqual((p["ComputerNameMode"], p["ColorMode"], p["SystemColorTheme"]), ("Custom", "Custom", "Dark"))
        self.assertNotIn("TimeZoneMode", p)


class Scripts(unittest.TestCase):
    def items(self):
        return [("battlenet", {"file": "battlenet-2.exe", "type": "exe",
                               "args": '--lang=enUS --installpath="%PROGRAMFILES(X86)%\\Battle.net"'}),
                ("epic", {"file": "epic-1.msi", "type": "wix", "args": "/quiet /norestart"}),
                ("claude", {"file": "Claude.msix", "type": "msix", "args": ""}),
                ("claude-code", {"file": "claude.exe", "type": "claude-code", "args": ""}),
                ("winget:Some.App", {"file": "winget-Some.App-1.exe", "type": "nullsoft", "args": "/S"})]

    def test_install_script(self):
        ps = winprep.install_script(self.items())
        self.assertIn("ExpandEnvironmentVariables('--lang=enUS --installpath=\"%PROGRAMFILES(X86)%\\Battle.net\"')", ps)
        self.assertIn("Run 'Epic Games Launcher' 'msiexec.exe' ('/i \"{0}\" /quiet /norestart' -f (Join-Path $dir 'epic-1.msi'))", ps)
        self.assertIn("Add-AppxPackage -Path (Join-Path $dir 'Claude.msix')", ps)
        self.assertIn("& (Join-Path $dir 'claude.exe') install", ps)
        self.assertIn("Run 'Some.App' (Join-Path $dir 'winget-Some.App-1.exe') '/S'", ps)
        self.assertNotIn('"$label:', ps)  # PowerShell would read that as a scoped variable
        self.assertEqual(ps.count("if (-not (Signed "), 4)  # every installer but the MSIX
        self.assertEqual(ps.count("{"), ps.count("}"))

    def test_toolchain_kinds(self):
        sha = "ab" * 32
        items = [("toolchain:gl", {"file": "gl.zip", "type": "zip", "args": "", "sha256": sha, "nested": ["gl.exe"]}),
                 ("toolchain:age", {"file": "age.zip", "type": "zip", "args": "", "sha256": sha,
                                    "nested": ["age/age.exe", "age/age-keygen.exe"]}),
                 ("toolchain:jq", {"file": "jq.exe", "type": "portable", "args": "", "sha256": sha, "alias": "jq"}),
                 ("toolchain:7z", {"file": "7z.exe", "type": "exe", "args": "/S", "sha256": sha,
                                   "win_dir": r"%ProgramFiles%\7-Zip"}),
                 ("toolchain:py", {"file": "py.msix", "type": "msix", "args": "", "sha256": sha, "post": "& py.exe x"})]
        with mock.patch.object(winprep, "app_spec", lambda n: {"label": n.split(":")[1]}):
            ps = winprep.install_script(items)
        self.assertEqual(ps.count("(Hashed "), 4)  # zip, portable and the unsigned exe; not the MSIX
        self.assertNotIn("Signed '", ps)
        self.assertIn("AddPath (Join-Path $tools 'toolchain-gl')", ps)
        self.assertIn("AddPath (Join-Path (Join-Path $tools 'toolchain-age') 'age')", ps)
        self.assertEqual(ps.count("toolchain-age') 'age')"), 1)  # one PATH entry per directory
        self.assertIn(r"(Join-Path $tools 'bin\jq.exe')", ps)
        self.assertIn(r"AddPath '%ProgramFiles%\7-Zip'", ps)
        self.assertIn("& py.exe x; $report += 'py: setup exit code ' + $LASTEXITCODE", ps)
        self.assertEqual(ps.count("{"), ps.count("}"))

    def test_quotes_escaped(self):
        self.assertEqual(winprep.ps_quote("it's"), "'it''s'")

    def test_keys_script(self):
        conf = dict(winprep.DEFAULTS, KEYS_VOLUME="Backup", KEYS_DIR="Git", GIT_NAME="O'Brien", GIT_EMAIL="a@example.com")
        ps = winprep.keys_script(conf)
        self.assertIn("$label = 'Backup'; $sub = 'Git'", ps)
        self.assertIn("user.name 'O''Brien'", ps)
        self.assertIn("core.sshCommand 'C:/Windows/System32/OpenSSH/ssh.exe'", ps)
        self.assertNotIn("Get-Volume", winprep.keys_script(dict(winprep.DEFAULTS)))


OSSL = """Message digest algorithm  : SHA256
Current message digest    : {cur}
Calculated message digest : {calc}

Signer's certificate:
\t------------------
\tSigner #0:
\t\tSubject: CN=Valve Corp.,O=Valve Corp.,L=Bellevue,C=US
\t\tIssuer : CN=Some CA
{tail}
"""


class Authenticode(unittest.TestCase):
    def check(self, rc, cur="AA", calc="AA", tail="Signature verification: ok"):
        out = subprocess.CompletedProcess([], rc, OSSL.format(cur=cur, calc=calc, tail=tail), "")
        with mock.patch.object(winprep.shutil, "which", return_value="/bin/osslsigncode"), \
                mock.patch.object(winprep, "ca_bundle", return_value="/ca.pem"), \
                mock.patch.object(winprep.subprocess, "run", return_value=out):
            return winprep.authenticode("f.exe")

    def test_valid(self):
        self.assertEqual(self.check(0), ("ok", "CN=Valve Corp.,O=Valve Corp.,L=Bellevue,C=US"))

    def test_intact_but_root_not_in_bundle(self):
        self.assertEqual(self.check(1, tail="Signature verification: failed")[0], "untrusted")

    def test_tampered(self):
        self.assertEqual(self.check(1, cur="AA", calc="BB", tail="")[0], "invalid")


class Config(unittest.TestCase):
    def test_parse_conf(self):
        conf = winprep.parse_conf('# c\nACCOUNT="Ivan Z"  # name\nAPPS="git  steam"\nEMPTY=""\n')
        self.assertEqual(conf, {"ACCOUNT": "Ivan Z", "APPS": "git  steam", "EMPTY": ""})

    def test_unknown_app_rejected(self):
        with self.assertRaises(SystemExit):
            winprep.app_names(dict(winprep.DEFAULTS, APPS="git nope"))
        self.assertEqual(winprep.app_names(dict(winprep.DEFAULTS, APPS="git winget:Some.App")), ["git", "winget:Some.App"])

    def test_toolchain_group(self):
        names = winprep.app_names(dict(winprep.DEFAULTS, APPS="git toolchain winget:jqlang.jq"))
        self.assertEqual(names[0], "git")
        self.assertNotIn("toolchain:git", names)  # same package as the catalog's git
        self.assertNotIn("winget:jqlang.jq", names)  # same package as toolchain:jq
        self.assertIn("toolchain:python3", names)
        self.assertEqual(winprep.app_spec("toolchain:pwsh")["prefer"], "wix")
        names = winprep.app_names(dict(winprep.DEFAULTS, APPS="7zip toolchain"))
        self.assertEqual(names[0], "7zip")
        self.assertNotIn("toolchain:7z", names)  # same package as the catalog's 7zip

    def test_runtimes_group(self):
        names = winprep.app_names(dict(winprep.DEFAULTS, APPS="runtimes winget:Microsoft.XNARedist"))
        self.assertEqual(len(names), len(winprep.RUNTIMES))
        self.assertIn("winget:Microsoft.VCRedist.2005.x86", names)
        self.assertEqual(winprep.app_spec("winget:Microsoft.DirectX")["prefer"], "exe")


class Tune(unittest.TestCase):
    def test_call_quotes_every_setting(self):
        conf = dict(winprep.DEFAULTS, TASKBAR_PINS="File Explorer, Ivan's App", STORE_APPS="")
        call = winprep.tune_call(conf, "(Join-Path $dir 'tune-windows.ps1')")
        self.assertTrue(call.startswith("& (Join-Path $dir 'tune-windows.ps1') -Taskbar 'center autohide alltray'"))
        self.assertIn("-Pins 'File Explorer, Ivan''s App'", call)
        self.assertIn("-StoreApps ''", call)
        self.assertIn("-Power '' -Apollo ''", call)
        self.assertNotIn("-Log", call)

    def test_install_script_tunes_before_keys(self):
        script = winprep.install_script([], tune="& 'tune.ps1'")
        self.assertLess(script.index("& 'tune.ps1' | ForEach-Object"), script.index("restore-keys.ps1"))
        self.assertNotIn("tune", winprep.install_script([]))


if __name__ == "__main__":
    unittest.main()
