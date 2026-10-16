#version 420
uniform sampler2D sTD2DInputs[1];uniform vec3 uTimeResolution;
#ifndef uBrightness
#define uBrightness 0.0
#endif
#ifndef uContrast
#define uContrast 1.0
#endif
#ifndef uSaturation
#define uSaturation 1.0
#endif
#ifndef uGamma
#define uGamma 1.0
#endif
out vec4 outColor0;void main(){vec3 color=pow(texture(sTD2DInputs[0],gl_FragCoord.xy/uTimeResolution.yz).xyz,vec3(uGamma));color=mix(vec3(1.0)*dot(vec3(0.3086,0.6094,0.0820),color),color,uSaturation);outColor0=vec4(color*uContrast+(1.0-uContrast)*0.5+uBrightness,1.0);
#define saturate(x) clamp(x,0,1)
#define uTime uTimeResolution.x
float fade=saturate(uTime*0.25);const float endOfDemo=554.0/80.0*60.0;if(uTime<endOfDemo)fade*=saturate(abs(uTime-endOfDemo)*0.5-0.5);else
fade*=saturate(uTime-endOfDemo-1.5);const float endOfCredits=597.0/80.0*60.0;fade*=saturate(endOfCredits-uTime);outColor0=saturate(outColor0)*fade;}
