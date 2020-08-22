# This file is part of pymadcad,  distributed under license LGPL v3

from .mathutils import vec3, mat3, dmat3, dvec3, dot, cross, project, noproject, anglebt, sqrt, cos, acos, asin, spline, interpol1, normalize, distance, length, inverse, transpose, NUMPREC, COMPREC
from .mesh import Mesh, Web, Wire, lineedges, connef, suites, line_simplification
from . import generation as gt
from . import text
from . import settings

__all__ = [	'chamfer', 'bevel', 'beveltgt', 
			'tangentjunction', 'cut', 'cutsegments', 'planeoffsets',
			'cut_width', 'cut_distance', 'cut_depth', 'cut_angle',
			]

# ---- cut methods -----

def cut_width(width, fn1, fn2):
	''' plane offset for a cut based on the width of the bevel '''
	n = normalize(fn1+fn2)
	s = dot(fn1,n)
	return -width/2 * sqrt(1/s**2 - 1) * n

def cut_distance(depth, fn1, fn2):
	''' plane offset for a cut based on the distance along the side faces '''
	return -depth * normalize(fn1+fn2)

def cut_depth(dist, fn1, fn2):
	''' plane offset for a cut based on the distance to the cutted edge '''
	return -dist * cross(normalize(cross(fn1,fn2)), fn1-fn2)

def cut_angle(depth, fn1, fn2):
	''' plane offset for a cut based on the angle between faces '''
	s = dot(fn1,n)
	return -depth/2 * (1/s - s) * n

# ----- user functions ------

def chamfer(mesh, line, cutter):
	''' create a chamfer on the given suite of points, create faces are planes.
		cutter is described in function planeoffsets()
	'''
	# cut faces
	segments = cut(mesh, line, planeoffsets(mesh, line, cutter))
	
	# create junctions
	group = len(mesh.groups)
	mesh.groups.append('junction')
	for i,s in enumerate(segments):
		if s:
			lp = []
			for part in suites(s):
				lp.extend(part)
			faces = gt.flatsurface(Wire(mesh.points, lp)).faces
			mesh.faces.extend(faces)
			mesh.tracks.extend([group]*len(faces))

def chamfer(mesh, edges, cutter):
	''' create a chamfer on the given suite of points, create faces are planes.
		cutter is described in function planeoffsets()
	'''
	normals = mesh.vertexnormals()
	corners = {}
	offs = []
	lines = suites(edges)
	for line in lines:
		offsets = planeoffsets(mesh, line, cutter)
		offs.append(offsets)
		corners[line[0]]  = min(corners.get(line[0], 0), dot(offsets[0], offsets[0]) /dot(offsets[0],  normals[line[0]]))
		corners[line[-1]] = min(corners.get(line[-1],0), dot(offsets[-1],offsets[-1])/dot(offsets[-1], normals[line[-1]]))
	# cut faces
	segments = []
	for point,offset in corners.items():
		segments.extend(cut_corner(mesh, point, offset*normals[point]))
	for line, offsets in zip(lines, offs):
		segments.extend(cut(mesh, line, offsets))
	
	# create junctions
	#group = len(mesh.groups)
	#mesh.groups.append('junction')
	#for i,s in enumerate(segments):
		#if s:
			#lp = []
			#for part in suites(s):
				#lp.extend(part)
			#faces = gt.flatsurface(Wire(mesh.points, lp)).faces
			#mesh.faces.extend(faces)
			#mesh.tracks.extend([group]*len(faces))

				
def beveltgt(mesh, line, cutter, interpol=spline, resolution=None):
	''' create a round profile on the given suite of points, create faces form cylindric surfaces.
		tangents to cuted faces will be used for interpolation
		cutter is described in function planeoffsets()
		
		WARNING: the tangency to cuted faces can lead to weired geometries in case of concave shape
	'''
	# cut faces
	conn = connef(mesh.faces)
	segments = cut(mesh, line, planeoffsets(mesh, line, cutter), conn)
	conn = connef(mesh.faces)
	group = Mesh(groups=['junction'])
	tangents = {}
	tmatch = []
	
	for (a,b),s in zip(lineedges(line), segments):
		if not s:	continue
		
		dir = mesh.points[a] - mesh.points[b]
		
		lps = suites(s)
		if len(lps) == 1:
			mesh += gt.flatsurface(Wire(mesh.points, lps[0]))
		else:
			left,right = lps
			if dot(dir, mesh.points[left[1]] - mesh.points[left[0]]) > 0:
				left,right = right,left
			right.reverse()
			ll, lr = Wire(mesh.points, left).length(), Wire(mesh.points, right).length()
			match = list(gt.curvematch(Wire(mesh.points, left), Wire(mesh.points, right)))
			tmatch.extend(match)
			
			# create parameters for the round profiles
			x = 0
			for i in range(len(match)-1):
				e = (match[i+1][0], match[i][0])
				if e in conn:	tl = mesh.facenormal(conn[e])
				else:			tl = None
				e = (match[i][1], match[i+1][1])
				if e in conn:	tr = mesh.facenormal(conn[e])
				else:			tr = None
				x += distance(mesh.points[match[i+1][0]], mesh.points[match[i][0]]) / ll
				
				for j in (0,1):
					l,r = match[i+j]
					o = interpol1(mesh.points[a], mesh.points[b], x)
					plane = normalize(cross(mesh.points[r]-o, mesh.points[l]-o))
					if tl:	tangents[l] = normalize(cross(plane, tl)) + tangents.get(l, 0)
					if tr:	tangents[r] = normalize(cross(tr, plane)) + tangents.get(r, 0)
	
	mesh += tangentjunction(mesh.points, tmatch, tangents, resolution, interpol)
			
def bevel(mesh, line, cutter, interpol=spline, resolution=None):
	''' create a smooth interpolated profile at the given suite of points
		tangents to line's adjacents faces will be used for interpolation
		cutter is described in function planeoffsets()
		
		WARNING: to use tangents from line adjacents faces can lead to matter add in case of concave shape
	'''
	# cut faces
	conn = connef(mesh.faces)
	normals = []
	for e in lineedges(line):
		normals.append((
			mesh.facenormal(conn[(e[1],e[0])]),
			mesh.facenormal(conn[e]),
			))
	
	segments = cut(mesh, line, planeoffsets(mesh, line, cutter), conn)
	tangents = {}
	tmatch = []
	
	for (a,b),s,(nl,nr) in zip(lineedges(line), segments, normals):
		if not s:	continue
		
		lps = suites(s)
		if len(lps) == 1:
			# TODO
			pass
			#mesh += gt.flatsurface(Wire(mesh.points, lps[0]))
		elif len(lps) == 2:
			# match left and right lines
			left,right = lps
			if dot(mesh.points[a] - mesh.points[b], mesh.points[left[1]] - mesh.points[left[0]]) > 0:
				left,right = right,left
			right.reverse()
			match = list(gt.curvematch(Wire(mesh.points, left), 
									   Wire(mesh.points, right) ))
			tmatch.extend(match)
			
			# create parameters for the round profiles
			ll, lr = Wire(mesh.points, left).length(), Wire(mesh.points, right).length()
			x = 0.
			for i in range(len(match)):
				if i:	x += distance(mesh.points[match[i-1][0]], mesh.points[match[i][0]]) / ll
				l,r = match[i]
				o = interpol1(mesh.points[a], mesh.points[b], x)
				plane = normalize(cross(mesh.points[r]-o, mesh.points[l]-o))
				tangents[l] = normalize(cross(plane, nl)) + tangents.get(l, 0)
				tangents[r] = normalize(cross(nr, plane)) + tangents.get(r, 0)
		else:
			print('error in bevel: bevel sides are', lps)
	
	mesh += tangentjunction(mesh.points, tmatch, tangents, resolution, interpol)

def tangentjunction(points, match, tangents, resolution=None, interpol=spline):
	''' create a surface between interpolated curves for each match '''
	group = Mesh(groups=['junction'])
	# determine the number of segments
	div = 0
	for l,r in match:
		v = points[l]-points[r]
		a = anglebt(tangents[l], tangents[r])
		dist = distance(points[l], points[r]) / sqrt(2-2*cos(a)) * a
		tangents[l] = tl = normalize(tangents[l]) * dist
		tangents[r] = tr = normalize(tangents[r]) * dist
		angle = min(1, acos(dot(tl,tr)))
		dist = length(points[l]-points[r])
		ldiv = settings.curve_resolution(dist, angle, resolution)
		if ldiv > div:
			div = ldiv
	
	return gt.junctioniter(
			( ((points[r], tangents[r]), (points[l], tangents[l])) for l,r in match),
			div, interpol)


# ----- algorithm ------

def planeoffsets(mesh, line, cutter):
	''' compute the offsets for cutting planes using the given method 
		cutter is a tuple or a function
		
			- function(fn1,fn2) -> offset 		
				fn1, fn2 are the adjacents face normals
				offset is the distance from segment to plane times the normal to the plane
				
			- ('method', distance) 				
				the method is the string name of the method (a function named 'cut_'+method existing in this module)
				distance depends on the method and is the numeric parameter of the method
	'''
	cutter = interpretcutter(cutter)
	# get adjacent faces' normals to lines
	adjacents = ({}, {})	# (left adjacents, right adjacents)
	segts = segmentsdict(line)
	for f in mesh.faces:
		for e in ((f[0],f[1]), (f[1],f[2]), (f[2],f[0])):
			if e in segts:					adjacents[0][segts[e]] = mesh.facenormal(f)
			elif (e[1],e[0]) in segts:		adjacents[1][segts[(e[1],e[0])]] = mesh.facenormal(f)
	# compute offsets (displacement on depth)
	offsets = []
	for i in range(len(line)-1):
		fn1,fn2 = adjacents[0][i], adjacents[1][i]
		offset = cutter(fn1, fn2)		
		if dot(cross(fn1, fn2), mesh.points[line[i+1]]-mesh.points[line[i]]) < 0:
			offset = -offset
		offsets.append(offset)
	return offsets

def interpretcutter(cutter):
	if isinstance(cutter, tuple):
		func = globals()['cut_'+cutter[0]]
		arg = cutter[1]
		return lambda fn1,fn2: func(arg, fn1, fn2)
	elif callable(cutter):
		return cutter
	else:
		raise TypeError("cutter must be a callable or a tuple (name, param)")

def separators(mesh, line, offsets):
	''' separations between planes.
		planes are determined by the offsets to the lines
		segments are in format (origin, segt normal, axis direction)
	'''
	
	segments = []	# planes intersections  (origin, plane normal, axis direction)
	l = len(line)-1
	# there is an additional cut segment if the line is a loop
	for i in range(1, l if line[0]!=line[-1] else l+1):
		n1, n2 = offsets[(i-1)%l], offsets[i%l]
		# compute the intersection with the two neigh cut planes
		d = cross(n1, n2)
		if length(d) > mesh.precision():
			d = normalize(d)
			p = mesh.points[line[i]]
			intersect = vec3(inverse(transpose(dmat3(n1, n2, d))) * dvec3(
							dot(p+n1, n1), 
							dot(p+n2, n2), 
							dot(p, d)))
			n = normalize(cross(d, intersect-p))
			if dot(n, mesh.points[line[i]]-mesh.points[line[i-1]]) > 0:		n = -n
			segments.append((intersect, n, d))
		else:
			segments.append(None)
		'''
		# display cut planes in the mesh (debug)
		grp = len(debmesh.groups)
		debmesh.groups.append(None)
		m = len(debmesh.points)
		d = normalize(d)
		debmesh.points.append(p)
		debmesh.points.append(intersect+d)
		debmesh.points.append(intersect-d)
		debmesh.faces.append((m,m+1,m+2))
		debmesh.tracks.append(grp)
		'''
	
	# complete segments that cannot be computed locally (straight suite of points for example)
	for i in range(1,len(segments)):
		if not segments[i]:		segments[i] = segments[i-1]
	for i in reversed(range(len(segments)-1)):
		if not segments[i]:		segments[i] = segments[i+1]
	
	return segments


def cut_line(mesh, line, offsets, conn=None, prec=None):
	''' cut the mesh faces by planes, determined by the offsets to the lines '''
	
	removal = set()		# faces to remove that match no replacements
	result = []				# intersection segments for each offset
	if prec is None:	prec = mesh.precision()
	if conn is None:	conn = connef(mesh.faces)
	# segments planes and normals
	segments = separators(mesh, line, offsets)
	circular = line[0] == line[-1]
	
	# cut at each plane
	for i in range(1,len(edge)):
		# take segment limiting planes
		if circular:
			s1 = segments[i-2]
			s2 = segments[i-1]
		else:
			s1 = segments[i-2] if i >= 2 else None
			s2 = segments[i-1] if i <= len(segments) else None
			
		# propagate until cut
		results.append(cut_edge(mesh, edge, offsets[i-1], s1, s2, conn, prec))
			
	# simplify cuts
	merges = {}
	for i,grp in enumerate(result):
		reindex = line_simplification(Web(mesh.points, grp), prec)
		lines = []
		for a,b in grp:
			c,d = reindex.get(a,a), reindex.get(b,b)
			if c != d:	lines.append((c,d))
		result[i] = lines
		merges.update(reindex)
	# apply merges, but keeping the empty faces, to keep the removal list valid
	for i,f in enumerate(mesh.faces):
		mesh.faces[i] = (
			merges.get(f[0],f[0]),
			merges.get(f[1],f[1]),
			merges.get(f[2],f[2]),
			)
	
	# delete inside faces and empty ones
	removefaces(mesh, lambda fi: fi in removal or faceheight(mesh,fi) <= prec)
	
	return result
		
def cut_edge(mesh, edge, offset, s1, s2, conn, prec):
	''' propagation cut for an edge '''
	cutplane = (mesh.points[edge[0]]+offset, -normalize(offset))
	# prepare propagation
	seen = set()
	front = [(edge[i],edge[i-1]), (edge[i-1],edge[i])]
	intersections = set()
	while front:
		# propagation affairs
		frontedge = front.pop()
		
		if frontedge not in conn:	continue
		fi = conn[frontedge]
		if fi in seen:	continue
		f = mesh.faces[fi]
		
		# do not process empty faces (its a topology singularity), but propagate
		if faceheight(mesh, fi) <= prec:	
			seen.add(fi)
			for j in range(3):
				front.append((f[j],f[j-1]))
			continue
		
		# find the intersection of the triangle with the common axis to the two cutplanes (current and next)
		p = None
		if s2:				intersection_axis_face((s2[0], s2[2]), mesh.facepoints(fi))
		if s1 and not s2:	intersection_axis_face((s1[0], s1[2]), mesh.facepoints(fi))
		if p and distance(p, mesh.points[f[0]]) > prec and distance(p, mesh.points[f[1]]) > prec and distance(p, mesh.points[f[2]]) > prec:
			# mark cutplane change
			# empty faces can be generated, but they are necessary to keep the connectivity working
			pi = mesh.usepointat(p, prec)
			l = len(mesh.faces)
			unregisterface(mesh, conn, fi)				
			mesh.faces[fi] = (f[0], f[1], pi)
			mesh.faces.append((f[1], f[2], pi))
			mesh.faces.append((f[2], f[0], pi))
			mesh.tracks.append(mesh.tracks[fi])
			mesh.tracks.append(mesh.tracks[fi])
			registerface(mesh, conn, fi)
			registerface(mesh, conn, l)
			registerface(mesh, conn, l+1)
			front.append(frontedge)
		else:
			# mark this face as processed
			seen.add(fi)
			
			#scn3D.add(text.Text(
				#(mesh.points[f[0]] + mesh.points[f[1]] + mesh.points[f[2]]) /3,
				#'  '+str(fi),
				#8,
				#color=(0.1, 1, 0.4),
				#align=('left', 'center'),
				#))
			
			# point side for propagation
			goodside = [False]*3
			for j,pi in enumerate(f):
				goodside[j] = 	dot(mesh.points[pi]-cutplane[0], cutplane[1]) > -prec
			goodx = [False]*3
			for j,pi in enumerate(f):
				p = mesh.points[pi]
				goodx[j] = ( (not s1 or dot(p-s1[0], -s1[1]) >= -prec)
							and (not s2 or dot(p-s2[0],  s2[1]) >= -prec) )
			
			if not (goodside[0] or goodside[1] or goodside[2]):
				continue
			
			# intersections of triangle's edges with the plane
			cut = [None]*3
			for j,e in enumerate(((f[0],f[1]), (f[1],f[2]), (f[2],f[0]))):
				cut[j] = intersection_edge_plane(cutplane, (mesh.points[e[0]], mesh.points[e[1]]), prec)
			for j in range(3):
				if cut[j-1] and cut[j] and distance(cut[j-1], cut[j]) < prec:	cut[j] = None
			
			if goodside[0] and goodside[1] and goodside[2] and (goodx[0] or goodx[1] or goodx[2]):
				removal.add(fi)
			
			cutted = False
			# cut the face
			for j in range(3):
				if cut[j] and cut[j-1]:
					cutted = True
					# cut only if the intersection segment is in the delimited area
					if s1 and dot(cut[j-1]-s1[0],-s1[1]) < prec and dot(cut[j]-s1[0],-s1[1]) < prec:	continue
					if s2 and dot(cut[j-1]-s2[0], s2[1]) < prec and dot(cut[j]-s2[0], s2[1]) < prec:	continue
					
					# cut the face (create face even for non kept side, necessary for propagation)
					removal.discard(fi)
					p1 = mesh.usepointat(cut[j], prec)
					p2 = mesh.usepointat(cut[j-1], prec)
					unregisterface(mesh, conn, fi)
					l = len(mesh.faces)
					mesh.faces[fi] = (p1, f[j-2], f[j-1])
					mesh.faces.append((p1, f[j-1], p2))
					mesh.faces.append((p1, p2, f[j-0]))
					mesh.tracks.append(mesh.tracks[fi])
					mesh.tracks.append(mesh.tracks[fi])
					registerface(mesh, conn, fi)
					registerface(mesh, conn, l)
					registerface(mesh, conn, l+1)
					seen.update((fi, l, l+1))
					# remove the faces outside
					if dot(mesh.points[f[j]]-cutplane[0], cutplane[1]) < 0:
						removal.add(fi)
						removal.add(l)
						intersections.add((p2,p1))
					else:
						removal.add(l+1)
						intersections.add((p1,p2))
					break
			# propagate if the face has been cutted or has a corner in the area
			if cutted or (goodside[0] and goodx[0] or goodside[1] and goodx[1] or goodside[2] and goodx[2]):
				for j in range(3):
					front.append((f[j],f[j-1]))
	
	return intersections
	
def cut_corner(mesh, point, offset, conn, prec, removal):
	''' cut a mesh by the plane at an offset from the specified point (existing point in the mesh) '''
	cutplane = (mesh.points[point]+offset, -normalize(offset))
	
	# prepare propagation
	toremove = {}
	intersections = []
	edge = next(filter(lambda e: point in e, conn))
	seen = set()
	front = [edge, (edge[1], edge[0])]
	while front:
		# unstack
		edge = front.pop()
		if edge in seen:		continue
		seen.add(edge)
		if edge not in conn:	
			front.append((edge[1], edge[0]))
			continue
		
		fi = conn[edge]
		f = mesh.faces[fi]
		a,b = edge
			
		# find intersection with the offset plane
		pt = intersection_edge_plane(cutplane, (mesh.points[a], mesh.points[b]), prec)
		if pt and distance(pt, mesh.points[a]) > prec and distance(pt, mesh.points[b]) > prec:
			pi = mesh.usepointat(pt)
			c = None
			for c in f:
				if c != a and c != b:	break
			
			# cut face
			mesh.faces[fi] = (a,pi,c)
			mesh.faces.append((pi,b,c))
			mesh.tracks.append(mesh.tracks[fi])
			registerface(mesh, conn, fi)
			registerface(mesh, conn, len(mesh.faces)-1)
			
			# register intersection and the face to remove
			r,k = len(mesh.faces)-1, fi
			if (	dot(mesh.points[a]-cutplane[0], cutplane[1]) > prec 
				or	dot(mesh.points[b]-cutplane[0], cutplane[1]) < -prec):
				r,k = k,r
			if fi in toremove:	intersections.append((toremove[fi], pi))
			if k in toremove:	del toremove[k]
			toremove[r] = pi
		else:
			# faces on the way but not intersected are inside
			toremove[fi] = None
		
		# propagate
		goodside = [dot(mesh.points[f[i]]-cutplane[0], cutplane[1]) > prec		for i in range(3)]
		for i in range(3):
			if goodside[i-1] or goodside[i]:
				front.append((f[i], f[i-1]))
	
	# delete inside faces and empty ones
	#removefaces(mesh, removal.__contains__)
	removal.update(toremove)
	return intersections

def cut(mesh, edges, offsets, conn=None, prec=None, removal=None):
	if conn is None:	conn = connef(mesh.faces)
	if prec is None:	prec = mesh.precision()
	if removal is None:	t
		removal = set()
		final = True
	else:
		final = False
	normals = mesh.vertexnormals()
	juncconn = connpp(edges)
	
	separators = {}	# plans separateurs pour chaque arete
	for i, prox in juncconn.items():
		if len(prox) != 2:	continue
		plane = (pts[i], normalize(pts[prox[0]] - pts[prox[1]]))
		separators[(i,prox[0])] = plane
		separators[(i,prox[1])] = plane
	
	corners = {}	# offset pour chaque coin
	# pour chaque jonction
	for junc, prox in juncconn.items():
		if len(prox) < 3:	continue
		# calculer le plan de distance max demandé par les aretes adjacentes
		offset = offsets.get(junc, 0.)
		# pour chaque arete adjacente (dans chaque sens)
		for p in prox:
			for e in ((junc,p), (p,junc)):
				if e not in conn:	continue
				# calculer la distance
				a,b,c = arrangeface(conn[e], junc)
				n = mesh.facenormal((a,b,c))
				nb = normalize(cross(ab,n))
				nc = normalize(cross(ac,n))
				ib = nb**2 / dot(offsets[edgekey(a,b)], nb)
				ic = nb**2 / dot(offsets[edgekey(a,c)], nc)
				ai = (ib*dot(db,dc) + ic) / dot(nb,nc)
				offset = max(offset, ai * dot(normalize(pts[b]-pts[c]), normals[a]))
		# assignation du plan de coupe
		corners[junc] = offset
		plane = (pts[junc] - offset, normalize(offset))
		for p in prox:
			separators[(p,junc)] = plane
	
	outlines = []
	# couper les aretes
	for edge in edges:
		outline += cut_edge(mesh, edge, separators[edge], separators[(edge[1], edge[0])], 
								conn, prec, removal)
	# couper les sommets
	for corner,offset in corners.items():
		outline += cut_corner(mesh, corner, offset, 
								conn, prec, removal)
	if final:
		removefaces(mesh, removal)
	return outlines
	
	
def unproject(vec, dir):
	return vec**2 / dot(vec,dir) * dir

def arrangeface(f, p):
	if   p == f[1]:	return f[1],f[2],f[0]
	elif p == f[2]:	return f[2],f[0],f[1]
	else:			return f

def registerface(mesh, conn, fi):
	f = mesh.faces[fi]
	for e in ((f[0],f[1]), (f[1],f[2]), (f[2],f[0])):
		conn[e] = fi
		
def unregisterface(mesh, conn, fi):
	f = mesh.faces[fi]
	for e in ((f[0],f[1]), (f[1],f[2]), (f[2],f[0])):
		if e in conn:	del conn[e]

def segmentsdict(line):
	segments = {}
	for i in range(len(line)-1):
		segments[(line[i],line[i+1])] = i
	return segments

# return intersection of an edge with a plane, or None
def intersection_edge_plane(axis, edge, prec):
	dist = dot(axis[0]-edge[0], axis[1])
	compl = dot(axis[0]-edge[1], axis[1])
	if abs(dist) <= prec:		return edge[0]
	if abs(compl) <= prec:	return edge[1]
	if dist * compl > 0:	return None		# the segment doesn't reach the plane
	edgedir = edge[1]-edge[0]
	if abs(dot(edgedir, axis[1])) <= NUMPREC:	return None	# the segment is parallel to the plane
	edgedir = normalize(edgedir)
	return edge[0] + dist * edgedir / dot(edgedir, axis[1])

def intersection_axis_face(axis, face):
	coords = inverse(dmat3(face[1]-face[0], face[2]-face[0], axis[1])) * dvec3(axis[0] - face[0])
	if 0 < coords[0] and 0 < coords[1] and coords[0]+coords[1] < 1 :
		#return axis[0] - axis[1]*coords[2]	# can lead to huge precision loss when the triangle is thin
		return face[0] + coords[0]*(face[1]-face[0]) + coords[1]*(face[2]-face[0])
	else:
		return None


def removefaces(mesh, crit):
	''' remove faces whose indices are present in faces, (for huge amount, prefer pass faces as a set) '''
	newfaces = []
	newtracks = []
	for i in range(len(mesh.faces)):
		if not crit(i):
			newfaces.append(mesh.faces[i])
			newtracks.append(mesh.tracks[i])
	mesh.faces = newfaces
	mesh.tracks = newtracks

#def facesurf(mesh, fi):
	#o,x,y = mesh.facepoints(fi)
	#return length(cross(x-o, y-o))

#def faceangle(mesh, fi):
	#o,x,y = mesh.facepoints(fi)
	#return length(cross(normalize(x-o), normalize(y-o)))
	
def faceheight(mesh, fi):
	f = mesh.facepoints(fi)
	heights = [length(noproject(f[i-2]-f[i], normalize(f[i-1]-f[i])))	for i in range(3)]
	return min(heights)


