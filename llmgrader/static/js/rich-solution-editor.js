const MONACO_VS_PATH = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs";

function escapeHtml(text) {
    return (text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderMarkdownPreview(markdownText) {
    if (!window.marked) {
        return `<pre>${escapeHtml(markdownText)}</pre>`;
    }

    let renderedHtml = "";
    try {
        renderedHtml = window.marked.parse(markdownText || "", {
            gfm: true,
            breaks: true
        });
    } catch (err) {
        console.error("Markdown render failed:", err);
        return `<pre>${escapeHtml(markdownText)}</pre>`;
    }

    if (window.DOMPurify) {
        renderedHtml = window.DOMPurify.sanitize(renderedHtml);
    }

    const previewContainer = document.createElement("div");
    previewContainer.innerHTML = renderedHtml;

    if (window.hljs) {
        previewContainer.querySelectorAll("pre code").forEach((block) => {
            const languageClass = Array.from(block.classList)
                .find((className) => className.startsWith("language-"));

            if (languageClass) {
                const language = languageClass.slice("language-".length).toLowerCase();
                const hasLanguage = typeof window.hljs.getLanguage === "function" &&
                    Boolean(window.hljs.getLanguage(language));
                if (!hasLanguage && language === "systemverilog" &&
                    window.hljs.getLanguage("verilog")) {
                    block.classList.remove(languageClass);
                    block.classList.add("language-verilog");
                }
            }
            window.hljs.highlightElement(block);
        });
    }

    if (window.renderMathInElement) {
        window.renderMathInElement(previewContainer, {
            delimiters: [
                {left: "$$", right: "$$", display: true},
                {left: "\\[", right: "\\]", display: true},
                {left: "\\(", right: "\\)", display: false},
                {left: "$", right: "$", display: false}
            ],
            throwOnError: false
        });
    }

    return previewContainer.innerHTML;
}

function loadMonaco() {
    return new Promise((resolve, reject) => {
        if (window.monaco && window.monaco.editor) {
            resolve(window.monaco);
            return;
        }

        if (typeof window.require !== "function") {
            reject(new Error("Monaco loader is unavailable (require not found)."));
            return;
        }

        window.require.config({
            paths: {
                vs: MONACO_VS_PATH
            }
        });

        window.require(["vs/editor/editor.main"], () => {
            resolve(window.monaco);
        }, (err) => {
            reject(err || new Error("Failed to load Monaco editor."));
        });
    });
}

function applyWrapAroundSelection(editor, before, after, placeholder = "") {
    if (!editor) {
        return;
    }

    const model = editor.getModel();
    if (!model) {
        return;
    }

    const selection = editor.getSelection();
    if (!selection) {
        return;
    }

    const selectedText = model.getValueInRange(selection);
    const content = selectedText || placeholder;
    const nextText = `${before}${content}${after}`;

    editor.executeEdits("toolbar-wrap", [{
        range: selection,
        text: nextText,
        forceMoveMarkers: true
    }]);

    const startPosition = selection.getStartPosition();
    const startOffset = model.getOffsetAt(startPosition);
    const anchorOffset = startOffset + before.length;
    const headOffset = anchorOffset + content.length;

    editor.setSelection({
        startLineNumber: model.getPositionAt(anchorOffset).lineNumber,
        startColumn: model.getPositionAt(anchorOffset).column,
        endLineNumber: model.getPositionAt(headOffset).lineNumber,
        endColumn: model.getPositionAt(headOffset).column
    });

    editor.focus();
}

function insertCodeFence(editor, language = "python", placeholder = "your_code_here") {
    applyWrapAroundSelection(editor, `\`\`\`${language}\n`, "\n```", placeholder);
}

function makeToolbarButton(label, title, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rich-solution-toolbar-btn";
    button.textContent = label;
    button.title = title;
    button.addEventListener("click", onClick);
    return button;
}

class MonacoSolutionEditor {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.onChange = options.onChange || null;
        this.editor = null;
        this.model = null;
        this.previewEnabled = window.innerWidth > 1100;
        this.disposed = false;
        this.pendingValue = this.textarea.value || "";

        this.buildShell();
        this.loadAndMount();
    }

    buildShell() {
        this.shell = document.createElement("div");
        this.shell.className = "rich-solution-editor-shell";

        this.toolbar = document.createElement("div");
        this.toolbar.className = "rich-solution-toolbar";

        this.workspace = document.createElement("div");
        this.workspace.className = "rich-solution-workspace";

        this.editorPane = document.createElement("div");
        this.editorPane.className = "rich-solution-editor-pane";

        this.previewPane = document.createElement("div");
        this.previewPane.className = "rich-solution-preview-pane";

        this.previewContent = document.createElement("div");
        this.previewContent.className = "rich-solution-preview-content";
        this.previewPane.appendChild(this.previewContent);

        this.workspace.appendChild(this.editorPane);
        this.workspace.appendChild(this.previewPane);

        this.shell.appendChild(this.toolbar);
        this.shell.appendChild(this.workspace);

        this.textarea.classList.add("rich-solution-hidden");
        this.textarea.insertAdjacentElement("afterend", this.shell);

        this.renderToolbar();
        this.updatePreviewVisibility();
        this.syncPreview(this.pendingValue);
    }

    renderToolbar() {
        const buttons = [
            makeToolbarButton("B", "Bold (Cmd/Ctrl+B)", () => {
                applyWrapAroundSelection(this.editor, "**", "**", "bold text");
            }),
            makeToolbarButton("I", "Italic (Cmd/Ctrl+I)", () => {
                applyWrapAroundSelection(this.editor, "*", "*", "italic text");
            }),
            makeToolbarButton("H", "Heading", () => {
                applyWrapAroundSelection(this.editor, "## ", "", "Heading");
            }),
            makeToolbarButton("Code", "Inline code", () => {
                applyWrapAroundSelection(this.editor, "`", "`", "code");
            }),
            makeToolbarButton("Block", "Code block", () => {
                insertCodeFence(this.editor);
            }),
            makeToolbarButton("SV Block", "SystemVerilog code block", () => {
                insertCodeFence(
                    this.editor,
                    "systemverilog",
                    "module top;\n  // your logic here\nendmodule"
                );
            }),
            makeToolbarButton("Link", "Insert link", () => {
                applyWrapAroundSelection(this.editor, "[", "](https://example.com)", "link text");
            }),
            makeToolbarButton("Inline Math", "Inline LaTeX", () => {
                applyWrapAroundSelection(this.editor, "$", "$", "x^2");
            }),
            makeToolbarButton("Block Math", "Block LaTeX", () => {
                applyWrapAroundSelection(this.editor, "$$\n", "\n$$", "E = mc^2");
            }),
            makeToolbarButton("Palette", "Open Command Palette (F1)", () => {
                if (this.editor) {
                    this.editor.focus();
                    try {
                        this.editor.trigger("toolbar", "editor.action.quickCommand");
                    } catch (err) {
                        console.warn("Command palette could not open:", err);
                    }
                }
            })
        ];

        this.previewToggleButton = makeToolbarButton("Preview", "Toggle split preview", () => {
            this.previewEnabled = !this.previewEnabled;
            this.updatePreviewVisibility();
            this.syncPreview();
        });
        this.previewToggleButton.classList.add("is-preview-toggle");

        buttons.forEach((button) => this.toolbar.appendChild(button));
        this.toolbar.appendChild(this.previewToggleButton);
    }

    async loadAndMount() {
        try {
            await loadMonaco();
            if (this.disposed) {
                return;
            }

            this.model = window.monaco.editor.createModel(this.pendingValue, "markdown");
            this.editor = window.monaco.editor.create(this.editorPane, {
                model: this.model,
                minimap: {enabled: false},
                lineNumbers: "on",
                wordWrap: "on",
                wrappingIndent: "same",
                automaticLayout: true,
                tabSize: 4,
                insertSpaces: true,
                autoClosingBrackets: "languageDefined",
                autoClosingQuotes: "never",
                autoIndent: "advanced",
                bracketPairColorization: {enabled: true},
                matchBrackets: "always",
                guides: {
                    bracketPairs: true,
                    indentation: true
                },
                quickSuggestions: {
                    other: true,
                    comments: true,
                    strings: true
                },
                suggestOnTriggerCharacters: true,
                smoothScrolling: true,
                scrollBeyondLastLine: false,
                renderWhitespace: "selection",
                padding: {top: 10, bottom: 10},
                fontFamily: "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Consolas, monospace",
                fontSize: 14,
                lineHeight: 22,
                theme: "vs"
            });

            this.editor.onDidChangeModelContent(() => {
                const value = this.getValue();
                this.textarea.value = value;
                this.syncPreview(value);
                if (typeof this.onChange === "function") {
                    this.onChange(value);
                }
            });

            this.editor.addCommand(window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.KeyB, () => {
                applyWrapAroundSelection(this.editor, "**", "**", "bold text");
            });
            this.editor.addCommand(window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.KeyI, () => {
                applyWrapAroundSelection(this.editor, "*", "*", "italic text");
            });

            this.syncPreview(this.pendingValue);
        } catch (err) {
            console.error("Monaco editor failed to initialize:", err);
        }
    }

    updatePreviewVisibility() {
        this.workspace.classList.toggle("is-preview-visible", this.previewEnabled);
        this.previewToggleButton.classList.toggle("is-active", this.previewEnabled);
        this.previewToggleButton.textContent = this.previewEnabled ? "Preview On" : "Preview Off";
    }

    syncPreview(rawText = null) {
        const markdownText = rawText === null ? this.getValue() : rawText;
        this.previewContent.innerHTML = renderMarkdownPreview(markdownText);
    }

    getValue() {
        if (this.editor) {
            return this.editor.getValue();
        }
        return this.pendingValue || this.textarea.value || "";
    }

    setValue(value) {
        const nextValue = value || "";
        this.pendingValue = nextValue;
        this.textarea.value = nextValue;

        if (this.editor) {
            const currentValue = this.editor.getValue();
            if (currentValue !== nextValue) {
                this.editor.setValue(nextValue);
            }
        }

        this.syncPreview(nextValue);
    }

    destroy() {
        this.disposed = true;

        if (this.editor) {
            this.pendingValue = this.editor.getValue();
            this.editor.dispose();
            this.editor = null;
        }
        if (this.model) {
            this.model.dispose();
            this.model = null;
        }

        this.textarea.value = this.pendingValue;

        if (this.shell && this.shell.parentNode) {
            this.shell.parentNode.removeChild(this.shell);
        }
        this.textarea.classList.remove("rich-solution-hidden");
    }
}

window.createStudentSolutionEditor = function createStudentSolutionEditor(textarea, options = {}) {
    return new MonacoSolutionEditor(textarea, options);
};

window.dispatchEvent(new Event("rich-solution-editor-ready"));
