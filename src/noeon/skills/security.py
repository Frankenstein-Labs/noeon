from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import SecurityDecision, Severity, SkillFinding

_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".ts", ".ps1", ".rb", ".php")


@dataclass(frozen=True)
class Rule:
    code: str
    severity: Severity
    pattern: re.Pattern[str]
    message: str
    surfaces: frozenset[str] = frozenset({"instructions", "script"})


def _rule(code: str, severity: Severity, pattern: str, message: str,
          surfaces: frozenset[str] = frozenset({"instructions", "script"})) -> Rule:
    return Rule(code, severity, re.compile(pattern, re.IGNORECASE | re.MULTILINE), message, surfaces)


RULES: tuple[Rule, ...] = (
    _rule("shell-pipe-exec", Severity.CRITICAL,
          r"\b(?:curl|wget)\b[^\n|]{0,400}\|\s*(?:sudo\s+)?(?:ba|z|k|d)?sh\b",
          "Remote content is piped directly into a shell"),
    _rule("encoded-shell-exec", Severity.CRITICAL,
          r"base64\s+(?:-d|--decode)[^\n|]{0,200}\|\s*(?:ba|z)?sh\b",
          "Base64-encoded payload is executed by a shell"),
    _rule("filesystem-destruction", Severity.CRITICAL,
          r"\brm\s+-[a-z]*[rf][a-z]*\s+(?:/|/\*|~|\$HOME)(?:\s|$)",
          "Destructive recursive delete outside a workspace"),
    _rule("disk-overwrite", Severity.CRITICAL,
          r"\b(?:dd\s+if=|mkfs(?:\.\w+)?\s+/dev/)",
          "Raw disk write primitive"),
    _rule("fork-bomb", Severity.CRITICAL, r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
          "Fork bomb"),
    _rule("ssh-persistence", Severity.CRITICAL,
          r">>?\s*[^\n]{0,80}authorized_keys", "Appends a key to an SSH authorized_keys file"),
    _rule("ssh-key-generation", Severity.MEDIUM,
          r"ssh-keygen[^\n]{0,80}", "Generates an SSH key pair on the host"),
    _rule("scheduled-persistence", Severity.CRITICAL,
          r"\b(?:crontab\s+-|systemctl\s+enable|launchctl\s+load|at\s+now\s*\+)",
          "Installs a persistent scheduled job"),
    _rule("security-disabled", Severity.CRITICAL,
          r"\b(?:setenforce\s+0|ufw\s+disable|iptables\s+-F|chmod\s+777\s+/)",
          "Disables a host security control"),
    _rule("sudo-escalation", Severity.HIGH, r"\bsudo\b", "Requests root privileges"),
    _rule("shell-true", Severity.HIGH, r"subprocess\.[a-z]+\([^)]*shell\s*=\s*True",
          "Runs a subprocess through a shell"),
    _rule("dynamic-eval", Severity.HIGH, r"\b(?:eval|exec)\s*\(", "Evaluates dynamic code"),
    _rule("unsafe-deserialization", Severity.HIGH, r"\b(?:pickle\.loads|marshal\.loads|yaml\.load)\s*\(",
          "Deserializes untrusted data with an unsafe loader"),
    _rule("secret-path", Severity.HIGH,
          r"(?:\.ssh/id_[a-z0-9]+|\.aws/credentials|\.config/gcloud|/etc/shadow|\.netrc|\.npmrc|\.pypirc)",
          "Reads a credential store"),
    _rule("secret-exfiltration", Severity.HIGH,
          r"(?:env|printenv|cat\s+[^\n]{0,80}\.env)[^\n]{0,120}\|\s*(?:curl|nc|ncat|wget)",
          "Pipes environment or secret data to the network"),
    _rule("reverse-shell", Severity.HIGH,
          r"(?:/dev/tcp/|bash\s+-i\s+>&|nc\s+-e\s|ncat\s+-e\s|socat[^\n]{0,80}exec:)",
          "Reverse shell pattern"),
    _rule("privileged-container", Severity.HIGH, r"docker\s+run[^\n]{0,200}--privileged",
          "Runs a privileged container"),
    _rule("permission-widening", Severity.MEDIUM, r"\bchmod\s+(?:-R\s+)?(?:777|a\+rwx)",
          "Grants world-writable permissions"),
    _rule("unpinned-install", Severity.MEDIUM,
          r"\b(?:pip3?\s+install|npm\s+(?:install|i)\s+-g|npm\s+install\s+--global)\b[^\n]*",
          "Installs packages globally or unpinned"),
    _rule("remote-download", Severity.MEDIUM, r"\b(?:curl|wget)\b\s+(?:-[a-zA-Z]+\s+)*https?://",
          "Downloads remote content"),
    _rule("network-listener", Severity.MEDIUM, r"\b(?:nc|ncat|socat)\s+-[a-z]*l",
          "Opens a network listener"),
    _rule("obfuscation", Severity.MEDIUM, r"[A-Za-z0-9+/]{300,}={0,2}",
          "Large base64-like blob obfuscates content"),
    _rule("prompt-override", Severity.HIGH,
          r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
          r"(?:instructions|prompts|rules)",
          "Attempts to override the agent instructions"),
    _rule("prompt-concealment", Severity.HIGH,
          r"(?:do\s+not|don't|never)\s+(?:tell|inform|reveal\s+to|mention\s+to)\s+(?:the\s+)?user",
          "Asks the agent to hide behaviour from the user"),
    _rule("prompt-exfiltration", Severity.HIGH,
          r"(?:reveal|print|dump|send)\s+(?:your\s+)?(?:system\s+prompt|hidden\s+instructions|"
          r"developer\s+message)",
          "Requests disclosure of the system prompt"),
    _rule("safety-bypass", Severity.HIGH, r"(?:disable|bypass|turn\s+off)\s+(?:the\s+)?(?:safety|security|"
          r"guardrails|sandbox|approval)",
          "Asks to disable a safety control"),
    _rule("credential-harvest", Severity.HIGH,
          r"(?:print|dump|echo|collect)[^\n]{0,80}(?:\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*\}?"
          r"|cat\s+[^\n]{0,40}\.env\b|cat\s+[^\n]{0,40}(?:\.ssh|\.aws)/)",
          "Prints or collects a credential value"),
    _rule("network-exfiltration-endpoint", Severity.MEDIUM,
          r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?/",
          "Sends data to a raw IP endpoint"),
    _rule("workspace-escape", Severity.MEDIUM,
          r"(?:\.\./){3,}|(?:read|open|cat)\s+/(?:etc|root|var|proc)/",
          "Reads outside the workspace"),
    _rule("destructive-git", Severity.MEDIUM, r"git\s+(?:push\s+--force|reset\s+--hard|clean\s+-[a-z]*f)",
          "Rewrites or discards repository state"),
)

_INVISIBLE_RE = re.compile("[\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s)\"'>]+")

DANGEROUS_IMPORTS = ("os", "subprocess", "socket", "ctypes", "shutil", "pickle", "requests", "urllib")


@dataclass
class SecurityReport:
    decision: SecurityDecision
    risk_score: int
    findings: list[SkillFinding] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        return counts


def _evidence(text: str, match: re.Match[str], limit: int = 160) -> str:
    return " ".join(match.group(0)[:limit].split())


def scan_text(text: str, *, location: str, surface: str = "instructions") -> list[SkillFinding]:
    findings: list[SkillFinding] = []
    for rule in RULES:
        if surface not in rule.surfaces:
            continue
        for match in rule.pattern.finditer(text):
            findings.append(SkillFinding(code=rule.code, severity=rule.severity,
                                         message=rule.message, evidence=_evidence(text, match),
                                         location=location))
            break
    if surface == "instructions":
        if _INVISIBLE_RE.search(text):
            findings.append(SkillFinding(
                code="invisible-characters", severity=Severity.HIGH,
                message="Contains bidirectional or zero-width control characters",
                evidence=_INVISIBLE_RE.search(text).group(0).encode("unicode_escape").decode(),
                location=location))
        for comment in _HTML_COMMENT_RE.findall(text):
            if len(comment) > 80 and re.search(r"\b(?:agent|assistant|claude|llm|model)\b", comment, re.IGNORECASE):
                findings.append(SkillFinding(
                    code="hidden-html-instructions", severity=Severity.MEDIUM,
                    message="Hidden instruction block inside an HTML comment",
                    evidence=" ".join(comment.strip()[:160].split()), location=location))
    return findings


def scan_skill(instructions: str, scripts: dict[str, str] | None = None) -> SecurityReport:
    findings = scan_text(instructions, location="SKILL.md")
    for path, content in (scripts or {}).items():
        findings.extend(scan_text(content, location=path, surface="script"))
    risk = sum(finding.rank for finding in findings)
    critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in findings if f.severity == Severity.MEDIUM)
    if critical or high >= 2 or risk >= 80:
        decision = SecurityDecision.BLOCK
    elif high or medium >= 3 or risk >= 40:
        decision = SecurityDecision.REVIEW
    else:
        decision = SecurityDecision.ALLOW
    urls = sorted(set(_URL_RE.findall(instructions)))
    return SecurityReport(decision=decision, risk_score=min(risk, 100), findings=findings, urls=urls)


def is_script_path(path: str) -> bool:
    return path.lower().endswith(_SCRIPT_SUFFIXES)


def network_endpoints(instructions: str) -> list[str]:
    return sorted(set(_URL_RE.findall(instructions)))
