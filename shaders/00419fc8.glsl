#version 450
uniform vec3 uTimeResolution;uniform sampler2D sTD2DInputs[3];out vec4 outColor0;void main(){vec2 uv=gl_FragCoord.xy/uTimeResolution.yz;outColor0=max(vec4(0),texture(sTD2DInputs[0],uv));outColor0+=max(vec4(0),texture(sTD2DInputs[1],uv))*outColor0.a;outColor0.a=texture(sTD2DInputs[2],uv).a;}
