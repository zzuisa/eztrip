import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fromNights,expandBlocks,shiftBoundary} from '../src/dom.js';
const selection={name:'Rome hotel',lat:41.9,lng:12.49,kind:'hotel'};
test('one selection fills a continuous stay instead of repeating nightly entry',()=>{
 const blocks=[{night_start:1,night_end:7,selection}];assert.equal(expandBlocks(blocks,7).length,7);assert.equal(expandBlocks(blocks,7).at(-1).night,7);
});
test('all nights must be covered exactly once before save',()=>{
 assert.equal(expandBlocks([{night_start:1,night_end:2,selection},{night_start:4,night_end:7,selection}],7),null);
 assert.equal(expandBlocks([{night_start:1,night_end:4,selection},{night_start:4,night_end:7,selection}],7),null);
 assert.equal(expandBlocks([{night_start:1,night_end:7,selection:null}],7),null);
});
test('dragging a boundary moves nights while preserving full coverage',()=>{
 const blocks=[{night_start:1,night_end:2,selection},{night_start:3,night_end:5,selection},{night_start:6,night_end:7,selection}];
 shiftBoundary(blocks,0,4);assert.equal(blocks[0].night_end,4);assert.equal(blocks[1].night_start,5);assert.equal(expandBlocks(blocks,7).length,7);
 shiftBoundary(blocks,0,99);assert.equal(blocks[0].night_end,4);shiftBoundary(blocks,0,-2);assert.equal(blocks[0].night_end,1);assert.equal(blocks[1].night_start,2);
});
test('existing nightly selections are preserved as consecutive blocks',()=>{
 const nights=Array.from({length:7},(_,i)=>({night:i+1,...selection,...(i>=4?{name:'Duomo',lat:45.46,lng:9.19}:{})}));
 const blocks=fromNights(nights,7,'Italy');assert.equal(blocks.length,2);assert.equal(blocks[0].night_end,4);assert.equal(blocks[1].night_start,5);assert.equal(expandBlocks(blocks,7).at(-1).name,'Duomo');
});

test('an area alone never completes a stay or enables saving',()=>{
 assert.equal(expandBlocks([{night_start:1,night_end:7,selection:{...selection,kind:'area'}}],7),null);
});
