import {EditorView,basicSetup} from 'codemirror';
import {javascript} from '@codemirror/lang-javascript';
import {keymap} from '@codemirror/view';
import {indentWithTab} from '@codemirror/commands';
import {HighlightStyle,syntaxHighlighting} from '@codemirror/language';
import {tags} from '@lezer/highlight';
export function createCodeEditor(parent,doc,onChange,nonce){
  const view=new EditorView({doc,parent,extensions:[basicSetup,javascript(),keymap.of([indentWithTab]),
    syntaxHighlighting(HighlightStyle.define([{tag:tags.keyword,color:'var(--blue)',fontWeight:'600'},{tag:tags.string,color:'var(--error)'},{tag:tags.number,color:'var(--blue)'},{tag:tags.comment,color:'var(--muted)',fontStyle:'italic'}])),
    EditorView.cspNonce.of(nonce),EditorView.contentAttributes.of({'aria-label':'JavaScript source'}),
    EditorView.updateListener.of(update=>{if(update.docChanged)onChange(update.state.doc.toString());}),
    EditorView.theme({'&':{fontSize:'13px',height:'min(60vh,620px)',border:'1px solid var(--line)',borderRadius:'6px'},
      '.cm-scroller':{fontFamily:'var(--utility)',overflow:'auto'},'.cm-content':{padding:'14px 0'},
      '.cm-gutters':{backgroundColor:'var(--bg)',color:'var(--muted)',borderColor:'var(--line)'},
      '.cm-activeLine,.cm-activeLineGutter':{backgroundColor:'var(--pale)'},'.cm-cursor':{borderLeftColor:'var(--ink)'}})]});
  return {getValue:()=>view.state.doc.toString(),focus:()=>view.focus(),destroy:()=>view.destroy()};
}
