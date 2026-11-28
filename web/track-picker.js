// Browsing the short list never starts a different track. Playback changes only
// through the existing play/track buttons; those changes centre the active row.
export class TrackPicker {
  constructor(list,count,reduced) {
    this.list=list;this.count=count;this.reduced=reduced;this.current=0;
    list.addEventListener('focusin',event=>{
      const row=event.target.closest('li');if(row&&event.target.matches(':focus-visible'))this.center(row,false);
    });
    list.addEventListener('keydown',event=>{
      if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
      event.preventDefault();
      const rows=[...list.children],focused=event.target.closest('li');
      const start=focused?rows.indexOf(focused):this.current;
      const index=event.key==='Home'?0:event.key==='End'?rows.length-1:Math.max(0,Math.min(rows.length-1,start+(event.key==='ArrowDown'?1:-1)));
      rows[index]?.querySelector('.track-name').focus({preventScroll:true});
      if(rows[index])this.center(rows[index],false);
    });
    this.resize=new ResizeObserver(()=>this.select(this.current,false));this.resize.observe(list);
  }
  center(row,animate) {
    const top=row.offsetTop-(this.list.clientHeight-row.offsetHeight)/2;
    this.list.scrollTo({top,behavior:animate&&!this.reduced.matches?'smooth':'auto'});
  }
  select(index,animate=true) {
    this.current=index;
    [...this.list.children].forEach((row,i)=>{
      row.classList.toggle('current',i===index);
      if(i===index)row.setAttribute('aria-current','true');else row.removeAttribute('aria-current');
    });
    this.count.textContent=this.list.children.length?`${index+1} / ${this.list.children.length}`:'';
    const row=this.list.children[index];if(row)this.center(row,animate);
  }
}
