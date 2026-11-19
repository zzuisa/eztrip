// Each leg computes its own camera. Never inherit the previous leg's zoom.
export function framePlaybackLeg(map,element,mapbox,leg,from,to,options={}) {
 if(!map||!element)return;
 const width=element.clientWidth||600,height=element.clientHeight||400;
 const side=width<480?32:64;
 const bottom=Math.min(Number(options.bottomInset)||0,height*.3);
 const padding={top:Math.min(side+40,height*.25),bottom:Math.min(side+bottom,height*.4),left:side,right:side};
 const bounds=new mapbox.LngLatBounds([from.lng,from.lat],[to.lng,to.lat]);
 for(const p of leg.path?.coords||[])if(Array.isArray(p)&&p.every(Number.isFinite))bounds.extend(p);
 const maxZoom=options.maxZoom||15;
 const bearing=options.bearing||0;
 const camera=map.cameraForBounds(bounds,{padding,maxZoom,bearing,pitch:options.pitch||0});
 if(!camera||!Number.isFinite(camera.zoom))return;
 map.stop();
 const zoom=Math.min(maxZoom,camera.zoom);
 leg.fixedCam=!options.follow||zoom<maxZoom-.5;
 leg.hold=options.reducedMotion?0:700;
 leg.duration=Math.max(leg.duration||0,options.reducedMotion?0:1500);
 map.easeTo({center:camera.center,zoom,pitch:options.pitch||0,bearing,padding,
  duration:options.reducedMotion?0:650,essential:true,easing:t=>1-Math.pow(1-t,3)});
}
