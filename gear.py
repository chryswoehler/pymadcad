from mathutils import pi, cos, sin, tan, acos, asin, sqrt, interpol1, vec2, vec3, dot, distance, mat2, transpose, inverse, dirbase, scaledir, translate, mat3_cast, mat4_cast, angleAxis, transform, NUMPREC
from mesh import Web
import settings
import generation


def geartooth(profile, sector, m=1, resolution=None):
	''' correct a profile to allow it to be used on a gear where the tooth holds the given angular sector
		the module m can be provided to adjust curve resolution if it depends on the scale
	'''
	# perimeter of the profile
	total = 0
	for i in range(1,len(profile)):
		total += distance(profile[i-1],profile[i])
	# circular discrete profile
	res = settings.curve_resolution(m, pi, resolution)
	tooth = [vec2(profile[0])]
	for i in range(1,len(profile)):
		a = profile[i-1]
		b = profile[i]
		div = int(res * distance(a,b)/total)
		tooth += [interpol1(a,b, j/(div+1))		for j in range(1,div+2)]
	changed = [False] * len(tooth)
	
	# correct the circular profile by removing intersections with the linear profile
	r = 1/sector
	rmin = min((y for x,y in profile))
	rmax = max((y for x,y in profile))
	# x is advancement of the gear (and rotation therefore)
	xlim = sqrt(1 - ((r+rmin)/(r+rmax))**2) * (r+rmax)
	x = 0
	i = 0
	while x >= -xlim:
		dx =  tooth[(i+1) % len(tooth)][0] - tooth[i % len(tooth)][0]
		if dx < 0:	dx += 1
		x -= dx
	while x <= xlim:
		dx =  tooth[(i+1) % len(tooth)][0] - tooth[i % len(tooth)][0]
		if dx < 0:	dx += 1
		
		# search intersections
		for k in range(len(tooth)):
			t = (-x + tooth[k][0])/r
			radial = vec2(sin(t), -cos(t))
			center = vec2(x, r)
			p = center + radial * (r+tooth[k][1])
			for j in range(len(profile)-1):
				a, b = profile[j] * vec2(1,-1), profile[j+1] * vec2(1,-1)
				# compute intersection of radial vector with segment
				u,v = inverse(mat2(radial, b-a)) * (b-center)
				if 0 <= v and v <= 1:
					d = u - r
					if d < tooth[k][1]:
						tooth[k][1] = d
						changed[k] = True
		x += dx
		i += 1
	return tooth, changed

def racktooth(inclin, h1, h2=None):
	''' profile for iso normed gear
		inclin      the contact angle
		h1          the exterior height/module of the tooth
		h2          the interior height/module of the tooth
	'''
	if h2 is None:	h2 = h1
	inclin = tan(inclin)
	profile = [vec2(0, h1), vec2(1/4-h1*inclin, h1), vec2(1/4+h2*inclin, -h2)]
	return profile + [vec2(1-x, y)  for x,y in reversed(profile)]

def gearprofile(profile, m, z, axis=(vec3(0,0,0), vec3(0,0,1)), align=vec3(1,0,0)):
	''' generate a circular gear profile using the tooth profile given 
		m		the module
		z		the number of tooth on the profile (int)
	'''
	web = Web(groups=['gear'])
	sector = 2*pi/z
	r = z*m / (2*pi)
	o = axis[0]
	x,y,_ = dirbase(axis[1], align)
	last = None
	for i in range(z):
		for a,p in profile:
			t = (i+a) * sector
			if t == last:	continue
			last = t
			d = r+p*m
			web.points.append(d*cos(t)*x + d*sin(t)*y + o)
	for i in range(len(web.points)-1):
		web.lines.append((i,i+1))
		web.tracks.append(0)
	web.lines[-1] = (i,0)
	return web
	

def gear(profile, m, z, b, spin=0, axis=(vec3(0,0,0), vec3(0,0,1)), align=vec3(1,0,0), resolution=None):
	line = gearprofile(profile, m, z, axis, align)
	spin = b * tan(spin) * 2*pi/ (z*m)
	div = settings.curve_resolution(b, spin, resolution) + 2
	def trans():
		for i in range(div):
			x = i/(div-1)
			yield transform((x-0.5)*b*axis[1]) * transform(angleAxis(x*spin, axis[1]))
			
	return generation.extrans(line, trans(), ((i,i+1) for i in range(div-1)))

def screwgear(profile, m, z, b, radius, n=1, axis=(vec3(0,0,0), vec3(0,0,1)), align=vec3(1,0,0), resolution=None):
	line = gearprofile(profile, m, z, axis, align)
	#r = z*m / (2*pi)		# gear primitive radius
	spin = n*b/(z*radius)	# spin angle for the extrusion
	angle = 2*asin(b/(2*radius))	# angular sector of the screw contact
	div = max(
			settings.curve_resolution(b, spin, resolution),
			settings.curve_resolution(angle*radius, angle, resolution),
			)+ 2
	def trans():
		for i in range(div):
			x = i/(div-1)
			t = (x-0.5)*angle
			s = 1 + radius*(1-cos(t)) * 2*pi/(z*m)
			h = radius*sin(t)
			yield transform(h*axis[1]) * transform(angleAxis(x*spin, axis[1])) * transform(s*scaledir(axis[1], 1/s))
			
	return generation.extrans(line, trans(), ((i,i+1) for i in range(div-1)))


if __name__ == '__main__':
	from mathutils import radians
	import numpy as np
	from matplotlib import pyplot as plt
	from time import time
	
	m = 1
	z = 8
	b = 3
	
	start = time()
	linear = racktooth(radians(20), 0.5, 0.3)
	angular, changed = geartooth(linear, 2*pi/z)
	print('computation time', time()-start)
	
	if True:
		plt.plot([p[0] for p in linear], [p[1] for p in linear], label='rack')
		plt.plot([p[0] for p in angular], [p[1] for p in angular], '.-', label='gear')
		plt.axes().set_aspect('equal')
		plt.figlegend()
		plt.show()
	
	if False:
		import sys, view
		from PyQt5.QtWidgets import QApplication
		
		
		#res = gear(angular, m, z, b)
		#res = gear(angular, m, z, b, spin=radians(30))
		res = screwgear(angular, m, z, b, 0.6*b, 3)
		res.check()
		assert res.issurface()
		
		app = QApplication(sys.argv)
		main = scn3D = view.Scene()
		#res.options['debug_display'] = True
		scn3D.add(res)
		scn3D.look(res.box())
		main.show()
		sys.exit(app.exec())
