import { editor, KeyMod as KM, KeyCode as KC } from "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/+esm"
import sheet2 from "https://cdn.jsdelivr.net/npm/vscode-codicons@0.0.17/dist/codicon.min.css" with { type: "css" };


document.adoptedStyleSheets.push(sheet2);


export class Editor {
    constructor(container, options) {
        this.container = container;
        this.options = options;

        this.setupElement();
        this.setupEditor();

        if (this.options.autofocus) {
            this.editor.focus();
        }
    }

    setupElement() {
        this.container.classList.add("grizzlaxy-editor-area");
    }

    trigger(func=null, params=null) {
        clearTimeout(this._timer);
        const changes = this.changes;
        this.changes = undefined;
        const sendContent = this.changesLength === false;
        this.options.onChange({
            content: sendContent ? this.editor.getValue() : null,
            delta: sendContent ? null : (changes || []),
            event: "change",
        });
        if (func) {
            func(params);
        }
    }

    onChange(evt) {
        if (!this.options.sendDeltas) {
            this.changesLength = false;
        }
        else if (this.changes === undefined) {
            this.changes = [];
            this.changesLength = 0;
        }
        if (this.changesLength !== false) {
            for (let chg of evt.changes) {
                this.changes.push([chg.rangeOffset, chg.rangeLength, chg.text]);
                this.changesLength += 7 + chg.text.length;
                if (this.changesLength > this.editor.getModel().getValueLength()) {
                    this.changesLength = false;
                }
            }
        }
        const debounce = this.options.onChangeDebounce;
        if (debounce) {
            clearTimeout(this._timer);
            this._timer = setTimeout(this.trigger.bind(this), debounce * 1000);
        }
        else {
            this.trigger();
        }
    }

    setupEditor() {
        this.editor = editor.create(this.container, this.options.editor);

        if (this.options.onChange) {
            this.editor.getModel().onDidChangeContent(
                this.onChange.bind(this),
            )
        }

        for (let [key, func] of Object.entries(this.options.bindings || ({}))) {
            let binding = 0;
            for (let part of key.split(/ *\+ */)) {
                binding = binding | (KM[part] || KC[part]);
            }
            this.editor.addCommand(
                binding,
                this.trigger.bind(this, func, {event: "command", key: key}),
            );
        }
    }
}
