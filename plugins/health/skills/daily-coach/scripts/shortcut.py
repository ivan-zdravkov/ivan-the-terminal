#!/usr/bin/env -S python3 -I
"""daily-coach: generate the iPhone "Health sync" shortcut, so nobody has to build it by hand. Stdlib only.

  shortcut.py build OUT.xml        the unsigned shortcut (XML plist), from config.env
  shortcut.py sign IN.xml OUT      sign it with RoutineHub's HubSign service (iOS only imports signed shortcuts;
                                   Apple's `shortcuts sign` needs a Mac). OUT is the .shortcut file to import.

What the shortcut does (references/iphone-health-sync.md has the why):
  1. stop if it uploaded in the last 2 hours (Shortcuts/health-sync-last.txt)
  2. at most every 6 hours, open the ring app and wait a minute, so the ring syncs to Health (ring-opened-last.txt)
  3. read the Health samples the coach uses, one 'type|start|end|value|unit|source' line each
  4. PUT them as one file to HEALTH_DIR/YYYY/MM/ in the HEALTH_REPO's GitHub repo; on success, note the time

Config (config.env): HEALTH_REPO (its GitHub remote names the repo), HEALTH_DIR, RING_APP (the ring app's bundle id),
RING_APP_NAME, HEALTH_TYPES (Find Health Samples picker labels, comma-separated).
The GitHub token is NOT in the file: the iPhone asks for it once, on import. The signing service sees everything else.
"""
import importlib.util
import plistlib
import re
import subprocess
import sys
import uuid
from pathlib import Path

_spec = importlib.util.spec_from_file_location("coach", Path(__file__).resolve().with_name("coach.py"))
coach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coach)

HUBSIGN = "https://hubsign.routinehub.services/sign"
NAME = "Health sync"
OBJ = "￼"  # where a variable sits inside a text field
UPLOAD_EVERY_MIN, RING_EVERY_MIN, RING_WAIT_S = 120, 360, 60
# Picker label -> (days back, newest N, group by day). Find Health Samples stops the whole shortcut when a type has no
# samples at all, so only list types the ring or phone actually writes (Health > Browse). Steps are summed per day,
# with empty days filled, so they are never empty; grouping other types would sum them (3910 bpm), so they stay raw.
TYPES = {"Sleep": (2, 150, False), "Heart Rate": (1, 150, False), "Heart Rate Variability": (7, 60, False),
         "Blood Oxygen": (7, 80, False), "Resting Heart Rate": (7, 10, False), "Respiratory Rate": (7, 60, False),
         "Body Temperature": (7, 10, False), "Wrist Temperature": (7, 10, False), "Weight": (30, 10, False),
         "Steps": (2, 2, True)}
DEFAULT_TYPES = "Sleep, Heart Rate, Heart Rate Variability, Blood Oxygen, Steps"
PROPS = ("Start Date", "End Date", "Value", "Unit", "Source")


def uid():
    return str(uuid.uuid4()).upper()


def out(u, name):
    return {"OutputName": name, "OutputUUID": u, "Type": "ActionOutput"}


def var(name, prop=None):
    v = {"Type": "Variable", "VariableName": name}
    if prop:
        v["Aggrandizements"] = [{"PropertyName": prop, "Type": "WFPropertyVariableAggrandizement"}]
    return v


def text(*parts):
    """A text field: plain strings and variables (out()/var() dicts) in order."""
    s, att = "", {}
    for p in parts:
        if isinstance(p, str):
            s += p
        else:
            att["{%d, 1}" % len(s)] = p
            s += OBJ
    return {"Value": {"attachmentsByRange": att, "string": s}, "WFSerializationType": "WFTextTokenString"}


def attach(v):
    return {"Value": v, "WFSerializationType": "WFTextTokenAttachment"}


def items(pairs):
    """A dictionary field (headers, JSON body): (key, text-field) pairs."""
    return {"Value": {"WFDictionaryFieldValueItems": [
        {"WFItemType": 0, "WFKey": text(k), "WFValue": v} for k, v in pairs]},
        "WFSerializationType": "WFDictionaryFieldValue"}


class Shortcut:
    def __init__(self):
        self.actions = []

    def add(self, ident, **params):
        params.setdefault("UUID", uid())
        self.actions.append({"WFWorkflowActionIdentifier": "is.workflow.actions." + ident,
                             "WFWorkflowActionParameters": params})
        return params["UUID"]

    def comment(self, s):
        self.add("comment", WFCommentActionText=s)

    def block(self, ident, **start):
        """Opens an If or Repeat; returns the function that closes it (and the closing action's UUID)."""
        group = uid()
        self.add(ident, GroupingIdentifier=group, WFControlFlowMode=0, **start)
        return lambda: self.add(ident, GroupingIdentifier=group, WFControlFlowMode=2)

    def if_(self, value, condition, **literal):
        return self.block("conditional", WFCondition=condition, WFInput={"Type": "Variable", "Variable": attach(value)},
                          **literal)

    def minutes_since_file(self, name, now_min):
        """Minutes since the stamp in Shortcuts/<name> (the caller guards for a missing file with if_ ... 100)."""
        f = self.add("documentpicker.open", WFFileErrorIfNotFound=False, WFShowFilePicker=False,
                     WFGetFilePath=text(name))
        return f, lambda: self.add("calculateexpression", Input=text(out(now_min, "Calculation Result"), "-(",
                                                                      out(f, "File"), ")"))

    def save_stamp(self, name, now_min):
        t = self.add("gettext", WFTextActionText=text(out(now_min, "Calculation Result")))
        self.add("documentpicker.save", WFInput=attach(out(t, "Text")), WFAskWhereToSave=False, WFSaveFileOverwrite=True,
                 WFFileDestinationPath=text(name))


def find_samples(sc, label, days, limit, by_day):
    params = dict(WFContentItemSortProperty="Start Date", WFContentItemSortOrder="Latest First",
                  WFContentItemLimitEnabled=True, WFContentItemLimitNumber=limit)
    if by_day:
        params.update(WFHKSampleFilteringGroupBy="Day", WFHKSampleFilteringFillMissing=True)
    return sc.add("filter.health.quantity", **params, WFContentItemFilter={
        "Value": {"WFActionParameterFilterPrefix": 1, "WFContentPredicateBoundedDate": False,
                  "WFActionParameterFilterTemplates": [
                      {"Bounded": True, "Operator": 4, "Property": "Type", "Removable": False,
                       "Values": {"Enumeration": {"Value": label, "WFSerializationType": "WFStringSubstitutableState"}}},
                      {"Operator": 1001, "Property": "Start Date", "Removable": True,  # is in the last N days
                       "Values": {"Number": str(days), "Unit": 16}}]},
        "WFSerializationType": "WFContentPredicateTableTemplate"})


def build(cfg, repo_slug):
    labels = [t.strip() for t in (cfg.get("HEALTH_TYPES") or DEFAULT_TYPES).split(",") if t.strip()]
    unknown = [t for t in labels if t not in TYPES]
    if unknown:
        raise ValueError(f"HEALTH_TYPES: unknown {unknown}; known: {', '.join(TYPES)}")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo_slug):
        raise ValueError(f"not a GitHub owner/repo: {repo_slug!r}")
    folder = cfg["HEALTH_DIR"].strip("/")
    sc = Shortcut()
    sc.comment(f"{NAME}: sends the last day of Health data to the private repo for the daily coach. Runs from "
               "app-opened automations; generated by daily-coach scripts/shortcut.py, so change it there, not here.")
    token = sc.add("gettext", WFTextActionText="")  # filled in on import (WFWorkflowImportQuestions), never in the file
    question = {"ParameterKey": "WFTextActionText", "Category": "Parameter", "ActionIndex": len(sc.actions) - 1,
                "Text": "GitHub token (fine-grained, this repo only, Contents read and write)", "DefaultValue": ""}

    # Minutes since an arbitrary point in the year as a plain number: no date parsing, no locale. New Year's makes the
    # difference hugely negative, which only means "long ago".
    now = sc.add("date", WFDateActionMode="Current Date")
    stamp = sc.add("format.date", WFDate=text(out(now, "Date")), WFDateFormatStyle="Custom",
                   WFDateFormat="D'*1440+'H'*60+'m")
    now_min = sc.add("calculateexpression", Input=text(out(stamp, "Formatted Date")))

    sc.comment(f"At most one upload every {UPLOAD_EVERY_MIN // 60} hours.")
    f, since = sc.minutes_since_file("health-sync-last.txt", now_min)
    end_file = sc.if_(out(f, "File"), 100)
    diff = since()
    end_recent = sc.if_(out(diff, "Calculation Result"), 1003, WFNumberValue=str(-UPLOAD_EVERY_MIN),
                        WFAnotherNumber=str(UPLOAD_EVERY_MIN))
    sc.add("exit")
    end_recent()
    end_file()

    app = cfg["RING_APP"].strip()
    if app:
        sc.comment(f"The ring app only pulls from the ring while it is open: open it at most every {RING_EVERY_MIN // 60} "
                   f"hours and give it {RING_WAIT_S} s. Leave it (back link or swipe home), don't force-quit it.")
        yes = sc.add("gettext", WFTextActionText="yes")
        sc.add("setvariable", WFVariableName="wake", WFInput=attach(out(yes, "Text")))
        f, since = sc.minutes_since_file("ring-opened-last.txt", now_min)
        end_file = sc.if_(out(f, "File"), 100)
        diff = since()
        end_recent = sc.if_(out(diff, "Calculation Result"), 1003, WFNumberValue=str(-RING_EVERY_MIN),
                            WFAnotherNumber=str(RING_EVERY_MIN))
        no = sc.add("gettext", WFTextActionText="no")
        sc.add("setvariable", WFVariableName="wake", WFInput=attach(out(no, "Text")))
        end_recent()
        end_file()
        end_wake = sc.if_(var("wake"), 4, WFConditionalActionString="yes")
        sc.add("openapp", WFAppIdentifier=app, WFSelectedApp={
            "BundleIdentifier": app, "Name": cfg["RING_APP_NAME"] or app, "TeamIdentifier": "0000000000"})
        sc.add("delay", WFDelayTime=RING_WAIT_S)
        sc.save_stamp("ring-opened-last.txt", now_min)
        end_wake()

    sc.comment("One line per sample: type|start|end|value|unit|source, dates in ISO 8601.")
    for label in labels:
        days, limit, by_day = TYPES[label]
        found = find_samples(sc, label, days, limit, by_day)
        group = uid()
        sc.add("repeat.each", GroupingIdentifier=group, WFControlFlowMode=0, WFInput=attach(out(found, "Health Samples")))
        dates = [sc.add("format.date", WFDate=text(var("Repeat Item", p)), WFDateFormatStyle="ISO 8601",
                        WFISO8601IncludeTime=True) for p in PROPS[:2]]
        sc.add("gettext", WFTextActionText=text(
            label, "|", out(dates[0], "Formatted Date"), "|", out(dates[1], "Formatted Date"), "|",
            var("Repeat Item", "Value"), "|", var("Repeat Item", "Unit"), "|", var("Repeat Item", "Source")))
        done = sc.add("repeat.each", GroupingIdentifier=group, WFControlFlowMode=2)
        sc.add("appendvariable", WFVariableName="health", WFInput=attach(out(done, "Repeat Results")))

    sc.comment("Commit it to the repo through the GitHub API.")
    body = sc.add("gettext", WFTextActionText=text(var("health")))
    b64 = sc.add("base64encode", WFEncodeMode="Encode", WFBase64LineBreakMode="None", WFInput=attach(out(body, "Text")))
    path = sc.add("format.date", WFDate=text(out(now, "Date")), WFDateFormatStyle="Custom",
                  WFDateFormat="yyyy/MM/yyyy-MM-dd_HHmmss")
    put = sc.add("downloadurl", WFHTTPMethod="PUT", WFHTTPBodyType="JSON",
                 WFURL=text(f"https://api.github.com/repos/{repo_slug}/contents/{folder}/", out(path, "Formatted Date"),
                            ".txt"),
                 WFHTTPHeaders=items([("Authorization", text("Bearer ", out(token, "Text"))),
                                      ("Accept", text("application/vnd.github+json")),
                                      ("X-GitHub-Api-Version", text("2022-11-28"))]),
                 WFJSONValues=items([("message", text("health sync")), ("content", text(out(b64, "Base64 Encoded")))]))
    commit = sc.add("getvalueforkey", WFGetDictionaryValueType="Value", WFDictionaryKey="commit",
                    WFInput=attach(out(put, "Contents of URL")))
    sc.comment("Only a successful upload counts: after a failure the next trigger tries again.")
    end_ok = sc.if_(out(commit, "Dictionary Value"), 100)
    sc.save_stamp("health-sync-last.txt", now_min)
    end_ok()

    return {
        "WFWorkflowActions": sc.actions,
        "WFWorkflowClientVersion": "2700.0.4",
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59446, "WFWorkflowIconStartColor": 4282601983},
        "WFWorkflowImportQuestions": [question],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": NAME,
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
    }


def repo_slug(repo):
    url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True,
                         check=True, creationflags=coach.NO_WINDOW).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise ValueError(f"HEALTH_REPO's origin is not a GitHub repo: {url}")
    return m.group(1)


def sign(xml_path, out_path):
    """HubSign's form (multipart: shortcutName, shortcut = the XML plist file) returns the signed file. Sent with curl
    (Windows 10+ and Linux ship it): the service redirects Python's own HTTP client to its home page, answers a JSON
    post (what Cherri sends) with the form, and fails on a name with a space. iOS names the import after the file."""
    r = subprocess.run(["curl", "-sS", "--max-time", "120", "-o", "-", "-F", f"shortcutName={NAME.replace(' ', '')}",
                        "-F", f"shortcut=@{Path(xml_path).as_posix()};type=application/xml", HUBSIGN],
                       capture_output=True, creationflags=coach.NO_WINDOW)
    signed = r.stdout
    if r.returncode or not signed.startswith(b"AEA1"):  # Apple Encrypted Archive: what a signed .shortcut is
        raise ValueError(f"the signing service returned no shortcut: {(r.stderr or signed)[:200]!r}")
    Path(out_path).write_bytes(signed)
    return len(signed)


def main(argv):
    cfg = coach.envfile.env(coach.CONF, {**coach.DEFAULTS, "RING_APP": "", "RING_APP_NAME": "", "HEALTH_TYPES": ""})
    try:
        if argv[:1] == ["build"] and len(argv) == 2:
            wf = build(cfg, repo_slug(coach.health_repo()))
            Path(argv[1]).write_bytes(plistlib.dumps(wf, fmt=plistlib.FMT_XML))
            print(f"{argv[1]}: {len(wf['WFWorkflowActions'])} actions")
        elif argv[:1] == ["sign"] and len(argv) == 3:
            print(f"{argv[2]}: {sign(argv[1], argv[2])} bytes, signed")
        else:
            sys.exit(__doc__)
    except (ValueError, OSError, subprocess.CalledProcessError) as ex:
        sys.exit(f"shortcut: {ex}")


if __name__ == "__main__":
    main(sys.argv[1:])
