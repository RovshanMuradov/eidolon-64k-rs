vec4 FogColor(vec3 direction){return vec4(mix(vec3(0.,0.,0.),vec3(0.15,0.1,0.4),pow(abs(direction.y),0.25)),2.);}
