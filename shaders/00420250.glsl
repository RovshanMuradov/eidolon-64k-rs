Material GetMaterial(Ray ray,Sample sampl){Material result=Material(vec3(0.1),0.0,0.0,0.0,vec3(0.0));if(sampl.materialId.w==0.0 || sampl.materialId.w==6.0){vec3 point=sampl.intersection;vec2 uv=point.xy;if(abs(sampl.normal.x)>abs(sampl.normal.z))uv.x=point.z;result.additive=texture(sTD2DInputs[3],uv*0.2).xyz*(1.0-abs(sampl.normal.y-0.4))*0.2;}else if(sampl.materialId.w==1.0)
{result.albedo=vec3(1.0);}else if(sampl.materialId.w==2.0)
{result.albedo=vec3(1.0,.15,0.1);}else if(sampl.materialId.w==3.0)
{result.albedo=vec3(2.0);result.reflectivity=0.5;}else if(sampl.materialId.w==5.0)
{result.albedo=vec3(0.0);float dampen=0.0;dampen=pow(saturate(1.0-sampl.fog),2.0);result.additive=vec3(1.2,0.5,0.2)*5.0*dampen;}else if(sampl.materialId.w==6.0)
{result.additive=smoothstep(0.0,0.02,sampl.materialId.x)*uHatchColor;}mtlMainBot(ray,sampl,result);mtlEvilBot(ray,sampl,result);return result;}
