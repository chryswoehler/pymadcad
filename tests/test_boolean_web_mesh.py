from madcad import *
from madcad.boolean import pierce, pierce_web_mesh, cut_web_mesh

mesh = extrusion(Z, Circle((O,Z),1), alignment=0.5)

others = {
	0: web(wire([vec3(-1, 0.5, 0), vec3(1, 0.2, 0)])),
	1: web(Softened([vec3(-2, 0, 0), vec3(-1, 0.5, 0), vec3(1, 0.2, 0), vec3(2, 3, 0)])),
	2: web(wire([vec3(-2,-0.5,0), vec3(2,-0.5,0), vec3(2,0.5,0), vec3(-2,0.5,0)]).close()),
	3: web(wire([vec3(-1,-0.5,0), vec3(1,-0.5,0), vec3(1,0.5,0), vec3(-1,0.5,0)]).close()),
	4: web([
		Segment(vec3(-1,-0.5,0), vec3(1,-0.5,0)), 
		Segment(vec3(1,0.5,0), vec3(-1,0.5,0)),
		]),
	}

results = []
for i, w in others.items():
	nprint('* w={} '.format(i))
	
	r = pierce(w, mesh, False)
	#r, frontier = cut_web_mesh(w, mesh)
	r.check()
	assert r.isline()
	results.append(Solid(content=r, mesh=mesh))
	
	r = pierce(w, mesh, True)
	#r, frontier = cut_web_mesh(w, mesh)
	r.check()
	assert r.isline()
	results.append(Solid(content=r, mesh=mesh))

for i, result in enumerate(results):
	result.position += 2*i*Y

show(results, options={'display_points':True})
