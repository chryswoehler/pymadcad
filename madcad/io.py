# This file is part of pymadcad,  distributed under license LGPL v3

import numpy as np
import numpy.lib.recfunctions as rfn
import os
import tempfile
from functools import wraps
from hashlib import md5
from types import ModuleType, FunctionType
from dataclasses import dataclass
from time import time
import sys
import weakref
import inspect

from .mathutils import vec3, glm, inf, typedlist
from .mesh import Mesh, Wire


class FileFormatError(Exception):	
	''' report an error about the support of a file format '''
	pass


def filetype(name, type=None):
	''' Get the name for the file format, using the given forced type or the name extension '''
	if not type:
		type = name[name.rfind('.')+1:]
	if not type:
		raise FileFormatError('unable to guess the file type')
	return type
	
def read(name: str, type=None, **opts) -> object:
	''' Load an arbitrary object (usually a mesh) from a file, guessing its file type 
	
		Parameters:
			name:  the path to the file to read
			type:  specify the file type to expect, it is deduced from file extension if not provided
			opts:  format specific settings for file loading
	'''
	type = filetype(name, type)
	reader = globals().get(type+'_read')
	if reader:
		return reader(name, **opts)
	else:
		raise FileFormatError('no read function available for format {}, did you installed its dependencies ?'.format(type))

def write(obj: object, name: str, type=None, **opts):
	''' Write an arbitrary object (usually a mesh) to a file, guessing its file type 
	
		Parameters:
			name:  the path to the file to write
			type:  specify the file type to produce, it is deduced from file extension if not provided
			opts:  format specific settings for object dumping
	'''
	type = filetype(name, type)
	writer = globals().get(type+'_write')
	if writer:
		return writer(obj, name, **opts)
	else:
		raise FileFormatError('no write function available for format {}, did you installed is dependencies ?'.format(type))


def module(file:str=None, name:str=None, code='') -> ModuleType:
	''' 
		execute the given file or code as a module and return it.
		
		The only difference wih `import` is that it will not be registered in `sys.modules` and therefore each time this function is called on the same file a duplicate is created.
		
		This function is useful if you want to import a python file which is not on the path or that you want being able to execute it multiple times
		
		Parameters:
			file: if provided, the content of the file at this path will be loaded as a new module
			name: the resulting module name, picked from the file name if not given
			code: a optional code snippet to execute in the module before interpreting the file
			
		Example:
		
			>>> foo1 = module('folder/foo.py')
			>>> foo2 = module('folder/foo.py')
			>>> foo1
			<module '<myfile/foo.py'>
			>>> foo2
			<module '<myfile/foo.py'>
			>>> foo1 is foo2
			False
			>>> 
			>>> foo.myfunc()
	'''
	if file:
		# load body and pick name from the file
		file = os.path.realpath(file)
		body = open(file, 'r').read()
		if not name:
			name = '<{}>'.format(file)
	else:
		# pick a default name juste like `exec` would have done
		if not name:
			name = '<string>'

	# create a regular python module, but not registered in sys.modules
	module = ModuleType(name)
	module.__name__ = name
	if file:
		module.__file__ = file

	if code:	exec(code, module.__dict__)	# first run provided code
	if file:	exec(body, module.__dict__) # then run loaded file
	return module



def cached(obj:callable=None, name:str=None, file=True, recursive=True) -> callable:
	'''
		Wrap a function and cache its results per set of arguments. The wrapped function is only called when either
		
		- no previous RAM or file cache exists for the given set of arguments
		- the existing cache is older than the source code of the generating function
			
		Note:
			Since a cache dump will be created each different arguments set used, we advice using this decorator only on functions that have simple arguments like integers and floats and when you know they will be used with not that many values
		
		Two cache storages are used: 
		
		- one on the hard disk
			in folder `cachedir`, it survives the program execution
		
		- one in RAM
			using a weak reference counting, which mean when all references to the cached object are dropped by the user code, the object is removed from RAM cache
		
		Parameters:
			obj:  the function to call to generate the data
			name:  the cache folder name, and cache RAM key, defaults to a dedicated subdirectory of directory set in `cachedir`
			file:  if True, a file will be used for caching, else only RAM cache will be done
			recursive:  if True, modifications of the dependencies of functions in modules coming from `cachedmodule` will also trigger calling the generating function
			
		Return:
			a function you can call with your desired set of arguments as the wrapped function, but with the caching checks added
			
		Warning:
			the returned functions results are references to the RAM cached objects, DO NOT MODIFY THEM
			
		Example:
		
			>>> @cached
			... def foo(a, b=0):
			... 	print('generate for', a, b)
			... 	return brick(width=vec3(1))
			>>> 
			>>> a = foo(1)   # first time, the code is executed
			generate for 1 0
			<Mesh ...>
			>>> b = foo(1)   # second time, cache is used
			<Mesh ...>
			>>> a is b
			True
			>>> c = foo(2, 3)  # first time for these arguments
			generate for 2 3
			<Mesh ...>
			
			>>> @cached('/tmp/mypart')
			... def foo(a, b=1):
			... 	return brick(width=vec3(1))
	'''
	if isinstance(obj, str): 
		name, obj = obj, None
	
	# directly called on a function
	if callable(obj):
		if name is None:
			name = '{}{}{}.{}'.format(cachedir, os.path.sep, 
				obj.__module__.replace('<', '').replace('>', '').replace('/', '_'), 
				obj.__qualname__.replace('<', '').replace('>', ''),
				)
		
		@wraps(obj)
		def caching(*args, **kwargs):
			# create a unique representation or arguments
			code_args = inspect.signature(obj).bind(*args, **kwargs)
			code_args.apply_defaults()
			code_args = sorted(list(code_args.arguments.items()))
			# the key for this cache
			if not os.path.exists(name):
				os.makedirs(name)
			unique = md5(repr(code_args).encode()).hexdigest()
			filename = '{}{}{}.pickle'.format(name, os.path.sep, unique)
			
			func_date = code_date(obj, recursive)
			
			# retreive from RAM cache
			ram = caches.get(filename)
			if ram and ram.date >= func_date:
				result = ram.finalizer.peek()[0]
			else:
				# retreive from file cache
				succeed = False
				if file:
					try:
						file_date = os.path.getmtime(filename)
						date = file_date
						if file_date >= func_date:
							result = pickle.load(open(filename, 'rb'))
							succeed = True
					except (OSError, pickle.UnpicklingError):
						pass
				
				# full computation
				if not succeed:
					date = time()
					result = obj(*args, **kwargs)
				
					# store to file cache
					if file:
						pickle.dump(result, open(filename, 'wb'))
				
				# store to RAM cache
				record(filename, date, result)
			
			return result
		return caching
			
	# used as a decorator
	elif obj is None:
		return partial(cache, name=name, target=target)
	# badly used
	else:
		raise TypeError("argument must be a filename or a function")
		
def cachedmodule(file:str, name:str=None, recursive=True) -> ModuleType:
	'''
		This function will call `module`, then all following calls with the same file name will return the same module object until the file or one of its former dependencies has been modified.
		
		Parameters:
			file:  the path to the file to load as a module
			name:  the resulting module name, picked from the file name if not given
			recursive:  if True, modifications of the dependencies of functions in modules coming from `cachedmodule` will also trigger reloading the module. Else only modifications to the given file will
		
		Warning:
			This will not take into account eventual new dependencies added to to this module, but only look up at the dependencies of the formerly loaded and cached module
			
		Example:
			
			>>> foo1 = cachedmodule('folder/foo.py')
			>>> foo2 = cachedmodule('folder/foo.py')
			>>> foo1 is foo2
			True
	'''
	if not name:
		name = '<{}>'.format(file)
	
	ram = caches.get(file)
	if ram:
		ram_data = ram.finalizer.peek()[0]
		file_date = code_date(ram_data, recursive)
		if ram.date >= file_date:
			return ram_data
	
	date = time()
	data = module(file, name)
	record(file, date, data)
	return data

@dataclass
class CacheRecord:
	''' convenient struct for logging caches '''
	date: float
	finalizer: weakref.finalize

# dictionnary of all caches, containing only instances of CacheRecord
caches = {}
# folder for default cache files
cachedir = tempfile.gettempdir() + '/madcad-cache'

def record(key, date, data):
	''' record a cache data in the caches dictionnary '''
	if previous := caches.pop(key, None):
		previous.finalizer.detach()
	caches[key] = CacheRecord(
		date,
		weakref.finalize(data, caches.pop, key),
		)

def code_date(func, recursive=False, memo=None) -> float:
	''' retreive the date of the latest change made to the given code (or its dependencies) '''
	# prevent dependency loops
	if memo is None:
		memo = {}
	elif last := memo.get(id(func)):
		return last
	
	# for builtin functions, we assume it is older than anything possible since they are standard and not supposed to vary
	date = -inf
	# retreive date from code file
	if isinstance(func, type):
		try: source = func.__init__
		except AttributeError: pass
		date = code_date(source, recursive, memo)
	elif isinstance(func, FunctionType):
		try: source = func.__globals__
		except AttributeError: pass
		date = module_date(source, recursive, memo)
	elif isinstance(func, ModuleType):
		try: source = func.__dict__
		except AttributeError: pass
		date = module_date(source, recursive, memo)
	else:
		return date
	
	return date
	
def module_date(obj: dict, recursive: bool, memo: dict) -> float:
	''' retreive from a module's dictionnary '''
	if last := memo.get(id(obj)):
		return last
	
	if file := obj.get('__file__'):
		try:
			date = os.path.getmtime(file)
		except OsError:
			date = -inf
	else:
		date = -inf
	
	# store date before recursive calls
	memo[id(obj)] = date
	# check functions used inside
	# imported modules are not recursed because they are supposed to be installed modules and thus not modified
	imported = sys.modules.get(obj.get('__name__'))
	if recursive and date != -inf and not (imported and imported.__dict__ is obj):
		for key, dependency in obj.items():
			date = max(date, code_date(dependency, recursive, memo))
	
	return date
		




'''
	pickle files are the standard python serialized files, they are absolutely not secure ! so do not use it for something else than your own caching.
'''
import pickle

def pickle_read(file, **opts):
	return pickle.load(open(file, 'rb'))
	
def pickle_write(obj, file, **opts):
	return pickle.dump(obj, open(file, 'wb'))

'''
	PLY is loaded using plyfile module 	https://github.com/dranjan/python-plyfile
	using the specifications from 	https://web.archive.org/web/20161221115231/http://www.cs.virginia.edu/~gfx/Courses/2001/Advanced.spring.01/plylib/Ply.txt
		(also locally available in ply-description.txt)
'''
try:
	from plyfile import PlyData, PlyElement
except ImportError:	pass
else:
	from . import triangulation

	def ply_read(file, **opts):
		mesh = Mesh()
		
		data = PlyData.read(file)
		if 'vertex' not in data:	raise FileFormatError('file must have a vertex buffer')
		if 'face' not in data:		raise FileFormatError('file must have a face buffer')
		
		# collect points
		mesh.points = typedlist(data['vertex'].data.astype('f8, f8, f8'), dtype=vec3)
		
		# collect faces
		faces = data['face'].data
		if faces.dtype.names[0] == 'vertex_indices':
			for face in faces['vertex_indices']:
				#print('  ', type(face), face, face.dtype, face.strides)
				if len(face) == 3:	# triangle
					mesh.faces.append(face)
				elif len(face) > 3:	# quad or other extended face
					mesh += triangulation.triangulation_outline(Wire(mesh.points, face))
		else:
			mesh.faces = numpy_to_typedlist(faces.astype('u4'), dtype=uvec3)

		# collect tracks
		if 'group' in faces.dtype.names:
			mesh.tracks = typedlist(faces['group'].astype('u4'), dtype='I')
		else:
			mesh.tracks = typedlist.full(0, len(mesh.faces), 'I')
		
		# create groups  (TODO find a way to get it from the file, PLY doesn't support non-scalar types)
		mesh.groups = [None] * (max(mesh.tracks, default=-1)+1)
		
		return mesh

	def ply_write(mesh, file, **opts):
		vertices = np.array(mesh.points, copy=False).astype(np.dtype([('x', 'f4'), ('y', 'f4'), ('z', 'f4')]))
		faces = np.empty(len(mesh.faces), dtype=[('vertex_indices', 'u4', (3,)), ('group', 'u2')])
		faces['vertex_indices'] = typedlist_to_numpy(mesh.faces, 'u4')
		faces['group'] = typedlist_to_numpy(mesh.tracks, 'u4')
		ev = PlyElement.describe(vertices, 'vertex')
		ef = PlyElement.describe(faces, 'face')
		PlyData([ev,ef], opts.get('text', False)).write(file)


'''
	STL is loaded using numpy-stl module 	https://github.com/WoLpH/numpy-stl
'''
try:	
	import stl
except ImportError:	pass
else:

	from .mathutils import *
	from .mesh import numpy_to_typedlist, typedlist_to_numpy
	def stl_read(file, **opts):
		stlmesh = stl.mesh.Mesh.from_file(file, calculate_normals=False)
		trinum = stlmesh.points.shape[0]
		mesh = Mesh(
			numpy_to_typedlist(stlmesh.points.reshape(trinum*3, 3), vec3), 
			typedlist(uvec3(i, i+1, i+2)  for i in range(0, 3*trinum, 3)),
			)
		mesh.options['name'] = stlmesh.name
		return mesh

	def stl_write(mesh, file, **opts):
		stlmesh = stl.mesh.Mesh(np.zeros(len(mesh.faces), dtype=stl.mesh.Mesh.dtype), name=mesh.options.get('name'))
		stlmesh.vectors[:] = typedlist_to_numpy(mesh.points, 'f4')[typedlist_to_numpy(mesh.faces, 'i4')]
		stlmesh.save(file, **opts)

'''
	OBJ is loaded using the pywavefront module	https://github.com/pywavefront/PyWavefront
	using the specifications from 	https://en.wikipedia.org/wiki/Wavefront_.obj_file
'''
try:
	import pywavefront
except ImportError:	pass
else:
	
	def obj_read(file, **opts):
		scene = pywavefront.Wavefront(file, parse=True, collect_faces=True)
		points = [vec3(v[:3]) for v in scene.vertices]
		faces = []
		for sub in scene.meshes.values():
			faces.extend(( tuple(f[:3]) for f in sub.faces ))
		mesh = Mesh(points, faces)
		if len(scene.meshes) == 1:
			mesh.options['name'] = next(iter(scene.meshes))
		return mesh
	
	# no write function available at this time
	#def obj_write(mesh, file, **opts):

'''
	JSON is loaded using the builtin json module
	always using the official json specifications
	it can store many object types, not only shapes
'''
import json

class JSONEncoder(json.JSONEncoder):
	def default(self, obj):
		if isinstance(obj, (vec2,vec3,vec4,mat2,mat3,mat4,quat)):
			return {'type':type(obj).__name__, 'content':list(obj)}
		elif isinstance(obj, np.ndarray):
			return {'type':'ndarray', 'dtype':obj.dtype, 'content':list(obj)}
		elif isinstance(obj, Mesh):
			return {'type':'Mesh', 'points': [tuple(p) for p in obj.points], 'faces':obj.faces, 'tracks':obj.tracks, 'groups':obj.groups}
		elif isinstance(obj, Web):
			return {'type':'Web', 'points': [tuple(p) for p in obj.points], 'edges':obj.edges, 'tracks':obj.tracks, 'groups':obj.groups}
		else:
			return json.JSONEncoder.default(self, obj)

def jsondecode(obj):
	if 'type' in obj:
		t = obj['type']
		if t in {'vec2','vec3','vec4','mat2','mat3','mat4','quat'}:		
			return vec3(obj['content'])
		elif t == 'ndarray':
			return np.array(obj['content'], dtype=obj['dtype'])
		elif t == 'Mesh':
			return Mesh([vec3(p) for p in obj['points']], [tuple(f) for f in obj['faces']], obj['tracks'], obj['groups'])
		elif t == 'Web':
			return Mesh([vec3(p) for p in obj['points']], [tuple(f) for f in obj['edges']], obj['tracks'], obj['groups'])
		else:
			raise FileFormatError('unable to load json for dumped type {}', t)
	return obj
	
def json_read(file, **opts):
	return json.load(open(file, 'r'), cls=JSONDecoder, **opts)

def json_write(objs, file, **opts):
	return json.dump(open(file, 'w'), object_hook=jsondecode, **opts)
