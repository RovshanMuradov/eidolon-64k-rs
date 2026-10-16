vec4 FogColor(vec3 direction){return vec4(CompositeSun(direction,sun_dir+vec3(0.0,0.7,0.0),mix(vec3(0.8,1.0,0.95),vec3(0.1,0.35,0.9),pow(max(0.0,direction.y),0.4))),2.0);}
