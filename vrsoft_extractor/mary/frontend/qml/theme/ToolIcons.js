// Shared tool -> Lucide kind mapping for activity rows. Every tool card picks
// its glyph from the same vocabulary T3 Code uses per call: terminal for
// commands, eye for reads, square-pen for edits, globe for web, wrench for
// MCP, hammer as the neutral fallback.
.pragma library

var aliases = {
    search: "search", globe: "globe", browser: "browser",
    document: "file", file: "file", files: "files", fileText: "fileText",
    terminal: "terminal", terminalPrompt: "terminal", command: "terminal",
    plug: "wrench", wrench: "wrench", hammer: "hammer", mcp: "wrench",
    robot: "agents", agents: "agents", subagent: "agents",
    fileDiff: "squarePen", edit: "squarePen", squarePen: "squarePen",
    listTodo: "listTodo", task: "listTodo", database: "database",
    code: "code", eye: "eye", check: "check"
}

var byItemType = {
    commandExecution: "terminal",
    fileRead: "eye",
    fileChange: "squarePen",
    webSearch: "globe",
    mcpToolCall: "wrench",
    browser: "browser",
    subagent: "agents"
}

function kindFor(item, fallback) {
    var entry = item || {}
    var state = String(entry.state || "")
    if (state === "error" || state === "failed") return "circleAlert"
    if (state === "waiting_approval") return "lock"
    // Lifecycle/status notes are informational checkpoints, not tool calls.
    if (String(entry.kind || "") === "status") return "check"
    var explicit = String(entry.icon || "")
    if (aliases[explicit] !== undefined) return aliases[explicit]
    var itemType = String(entry.itemType || entry.toolType || "")
    if (byItemType[itemType] !== undefined) return byItemType[itemType]
    var text = String(entry.text || entry.title || "").toLowerCase()
    if (text.indexOf("command") >= 0 || text.indexOf("terminal") >= 0
            || text.indexOf("git ") >= 0 || text.indexOf("running ") === 0
            || text.indexOf("execut") >= 0 || text.indexOf("comando") >= 0)
        return "terminal"
    return fallback !== undefined ? String(fallback) : "hammer"
}
