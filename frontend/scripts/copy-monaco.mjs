import {cpSync, mkdirSync} from "node:fs";
import {fileURLToPath} from "node:url";
const target=fileURLToPath(new URL("../public/monaco/vs",import.meta.url));
mkdirSync(target,{recursive:true});
cpSync(fileURLToPath(new URL("../node_modules/monaco-editor/min/vs",import.meta.url)),target,{recursive:true});
