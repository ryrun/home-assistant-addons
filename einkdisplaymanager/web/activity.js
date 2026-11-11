const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const size=n=>`${((n||0)/1024).toFixed(1)} KiB`;
const when=t=>t?new Date(t*1000).toLocaleString():'Not yet';
export const transferActive=t=>t?.status==='preparing'||t?.status==='sending';

export function transferHTML(t={status:'idle'},imageName=''){
  const active=transferActive(t), written=t.bytes_written||0,total=t.total_bytes||0;
  const labels={idle:'Waiting for a frame image request',preparing:'Preparing image for transfer',sending:'Sending image · HTTP',
    completed:'HTTP image delivery completed',unchanged:'Image unchanged · HTTP 304',interrupted:'Image transfer interrupted',failed:'Image could not be served'};
  const elapsed=t.elapsed_seconds??t.duration_seconds;
  return `<div class="transfer-state ${active?'is-active':''}" data-transfer-state="${escape(t.status)}"><strong>${escape(labels[t.status]||t.status)}</strong>
  ${imageName?`<p>Image: ${escape(imageName)}</p>`:''}
  ${active?`<progress ${total?`max="${total}" value="${written}"`:''} aria-label="Image bytes written by server"></progress>`:''}
  ${t.started_at?`<p>${when(t.started_at)}${elapsed!==undefined?` · ${Number(elapsed).toFixed(1)} s`:''}<br>${t.progress_known===false?`Byte count before restart unknown · output ${size(total)}`:`${size(written)} / ${size(total)} written by server`}</p>`:''}
  ${t.error_code?`<p>Error category: ${escape(t.error_code)}</p>`:''}
  <p class="help">${active?'Wait before resetting the physical frame or selecting another image. Progress counts bytes written by the server; the frame may still be receiving or processing them.':'HTTP completion is not confirmation of a physical display refresh. The add-on cannot observe on-device decoding or panel refresh.'}</p></div>`;
}

export function eventsHTML(events=[],entryName=()=>null){
  return events.length?[...events].reverse().map(e=>`<tr><td><time>${when(e.at)}</time></td><td>${escape(e.message)}<small>${escape(e.event)}${e.error_code?` · ${escape(e.error_code)}`:''}${e.entry_id?` · ${escape(entryName(e.entry_id)||e.entry_id)}`:''}</small></td><td>${e.http_status||'—'}</td><td>${e.bytes_written!==undefined?`${size(e.bytes_written)} / ${size(e.total_bytes)}`:''}${e.duration_seconds!==undefined?`<br>${Number(e.duration_seconds).toFixed(2)} s`:''}</td></tr>`).join(''):
    '<tr><td colspan="4">No events recorded yet. New authenticated frame requests and management actions will appear here.</td></tr>';
}
