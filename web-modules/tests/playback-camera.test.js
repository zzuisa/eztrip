import test from 'node:test';
import assert from 'node:assert/strict';
import {framePlaybackLeg} from '../src/playback-camera.js';

test('a local leg zooms back in after a long transfer in both camera modes',()=>{
 for(const follow of [false,true]){
  const moves=[];
  class Bounds{constructor(a,b){this.coords=[a,b]}extend(p){this.coords.push(p)}}
  const map={stop(){},cameraForBounds(bounds){const xs=bounds.coords.map(p=>p[0]);return {center:[0,0],zoom:Math.max(...xs)-Math.min(...xs)>1?5:15}},easeTo(camera){moves.push(camera)}};
  const options={follow,maxZoom:15,bottomInset:90};
  const far={duration:2000},near={duration:1000};
  framePlaybackLeg(map,{clientWidth:390,clientHeight:500},{LngLatBounds:Bounds},far,{lng:2,lat:48},{lng:12,lat:42},options);
  framePlaybackLeg(map,{clientWidth:390,clientHeight:500},{LngLatBounds:Bounds},near,{lng:12,lat:42},{lng:12.01,lat:42.01},options);
  assert.equal(moves[0].zoom,5);assert.equal(moves[1].zoom,15);
  assert.equal(far.fixedCam,true);assert.equal(near.fixedCam,!follow);
 }
});

test('curved route geometry is included and reduced motion avoids camera animation',()=>{
 let captured,move;
 class Bounds{constructor(a,b){this.coords=[a,b]}extend(p){this.coords.push(p)}}
 const map={stop(){},cameraForBounds(bounds){captured=bounds.coords;return {zoom:12,center:[1,2]}},easeTo(camera){move=camera}};
 const leg={path:{coords:[[0,0],[3,4],[1,1]]}};
 framePlaybackLeg(map,{clientWidth:320,clientHeight:300},{LngLatBounds:Bounds},leg,{lng:0,lat:0},{lng:1,lat:1},{reducedMotion:true});
 assert.ok(captured.some(p=>p[0]===3&&p[1]===4));assert.equal(move.duration,0);assert.equal(leg.hold,0);
});
