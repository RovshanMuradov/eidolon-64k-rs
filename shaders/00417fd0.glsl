float Bump(vec3 point,Ray ray,Sample sampl){if(sampl.materialId.w==3){vec2 uv=sampl.materialId.xz*0.3+point.xz;pR45(uv);float floor=texture(sTD2DInputs[2],uv).z;floor+=texture(sTD2DInputs[2],uv*4.0).z*0.05;floor+=texture(sTD2DInputs[0],uv*vec2(0.001,0.5)).z*0.1;return floor*0.01;}else if(sampl.materialId.w==2)
{return textureTri(sTD2DInputs[2],sampl.materialId.zyx*2.2+point,sampl.normal).z*0.01*(0.2+0.8*step(-0.9,-sampl.normal.z));}else if(sampl.materialId.w==15)
{return texture(sTD2DInputs[0],sampl.materialId.xz*0.8+point.xz).x*0.01;}return 0.0;}
