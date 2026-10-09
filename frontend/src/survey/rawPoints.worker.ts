import {prepareRawBuffer} from './rawPointData';
self.onmessage=(event)=>{
  const {id,buffer,origin,area,areas}=event.data;
  try{const positions=prepareRawBuffer(buffer,origin,area,areas);self.postMessage({id,positions}, {transfer:[positions.buffer]});}
  catch(e){self.postMessage({id,error:String(e)});}
};
