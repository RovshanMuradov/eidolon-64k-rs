vec4 FogColor(vec3 direction){return vec4(CompositeSun(direction,sun_dir+vec3(0.0,0.7,0.0),mix(vec3(218.0,240.0,255.0)/255.0,vec3(181.0,220.0,231.0)/255.0,pow(max(0.0,direction.y),.5))),2.0);}
