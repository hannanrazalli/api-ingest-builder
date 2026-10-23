"use client";
import Editor, {loader} from "@monaco-editor/react";
loader.config({paths: {vs: "/monaco/vs"}});
export default function CodeEditor({value, onChange, language="python", readOnly=false, theme="dark"}: {value: string; onChange?: (value: string) => void; language?: string; readOnly?: boolean; theme?: string}) {
  return <Editor height="100%" language={language} value={value} theme={theme === "light" ? "vs" : "vs-dark"} onChange={value => onChange?.(value ?? "")} loading={<div className="editor-loading">Loading local editor...</div>} options={{readOnly, minimap:{enabled:false}, fontSize:12, lineHeight:21, scrollBeyondLastLine:false, wordWrap:"on", padding:{top:18,bottom:18}, automaticLayout:true, tabSize:4, ariaLabel: readOnly ? "Generated Python code" : "Code input", renderLineHighlight:"none"}}/>;
}
