#version 450
uniform vec3 uTimeResolution;uniform sampler2D sTD2DInputs[1];out vec4 outColor0;void main(){vec2 uv=gl_FragCoord.xy/uTimeResolution.yz;outColor0=max(texture(sTD2DInputs[0],uv)-1.0,0.0);outColor0.a=1.0;}
