import test from 'node:test';
import assert from 'node:assert/strict';
import {recordPoint,grooveProgress,groovePitch} from '../web/record.js';

test('projected grooves seek to their audio time at desktop, mobile and zoom sizes',()=>{
  const turns=19.3;
  for(const [width,height,tilt] of [[1440,1440/2.65,.3],[390,210,.34],[2000,2000/2.65,.3]]) {
    const bounds={left:17,top:240,width,height};
    for(const reduced of [false,true]) for(const playing of [0,.23,.65,.98]) for(const desired of [.02,.3,.53,.9]) {
      const turn=desired*turns,radius=.47-(turn+.45)*groovePitch(turns);
      const angle=2*Math.PI*(turn-(reduced?0:playing*turns));
      const point=recordPoint(bounds.left+width*(.5+Math.sin(angle)*radius),bounds.top+height/2-width*tilt*Math.cos(angle)*radius,bounds,tilt);
      assert.ok(Math.abs(grooveProgress(point,playing,turns,reduced)-desired)<1e-10);
    }
  }
});

test('empty space above the projected disc is not an interactive groove',()=>{
  const point=recordPoint(195,10,{left:0,top:0,width:390,height:210},.34);
  assert.ok(point.r>.49);
});
