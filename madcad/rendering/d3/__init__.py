from ..base import *
from ...mathutils import *
from ... import settings
from ...common import resourcedir

import moderngl as mgl
import numpy.core as np

from copy import deepcopy
import traceback
from operator import itemgetter
from typing import Optional

# minimum opengl version required by the rendering pipeline
opengl_version = (3,3)
# shared open gl context, None if not yet initialized
global_context_3D = None

class Scene3D(Scene):
    ndims = 3
    overrides = {list: Group, dict: Group}


class Offscreen3D(Offscreen):
    '''
    A specialized Offscreen adding few methods specific to 3D
    '''
    def __init__(self, scene, size=uvec2(400,400), projection=None, navigation=None):
        global global_context_3D

        self.projection = projection or globals()[settings.scene['projection']]()
        self.navigation = navigation or globals()[settings.controls['navigation']]()

        # render parameters
        self.scene = scene if isinstance(scene, Scene3D) else Scene3D(scene)
        self.uniforms = {'proj':fmat4(1), 'view':fmat4(1), 'projview':fmat4(1)}    # last frame rendering constants
        self.targets = []
        self.steps = []
        self.step = 0
        self.stepi = 0

        # dump targets
        self.map_depth = None
        self.map_idents = None
        self.fresh = set()    # set of refreshed internal variables since the last render

        if global_context_3D:
            self.scene.ctx = global_context_3D
        else:
            self.scene.ctx = global_context_3D = mgl.create_standalone_context(requires=opengl_version)
        self.scene.ctx.line_width = settings.display["line_width"]

        self.init(size)
        self.preload()

    def init(self, size):
        w, h = size

        ctx = self.scene.ctx
        assert ctx, 'context is not initialized'

        # self.fb_frame is already created and sized by Qt
        self.fb_screen = ctx.simple_framebuffer(size)
        self.fb_ident = ctx.simple_framebuffer(size, components=3, dtype='f1')
        self.targets = [
            ('screen', self.fb_screen, self.setup_screen),
            ('ident', self.fb_ident, self.setup_ident)
        ]
        self.map_ident = np.empty((h, w), dtype='u2')
        self.map_depth = np.empty((h, w), dtype='f4')

    def preload(self):
        ''' Internal method to load common resources '''
        ctx, resources = self.scene.ctx, self.scene.resources
        resources['shader_ident'] = ctx.program(
            vertex_shader=open(resourcedir+'/shaders/object-ident.vert').read(),
            fragment_shader=open(resourcedir+'/shaders/ident.frag').read(),
        )

        resources['shader_subident'] = ctx.program(
            vertex_shader=open(resourcedir+'/shaders/object-item-ident.vert').read(),
            fragment_shader=open(resourcedir+'/shaders/ident.frag').read(),
        )

    def look(self, position: fvec3=None):
        ''' Make the scene navigation look at the position.
            This is changing the camera direction, center and distance.
        '''
        if not position:
            position = self.scene.box().center
        dir = position - fvec3(affineInverse(self.navigation.matrix())[3])
        if not dot(dir,dir) > 1e-6 or not isfinite(position):
            return

        if isinstance(self.navigation, Turntable):
            self.navigation.yaw = atan2(dir.x, dir.y)
            self.navigation.pitch = -atan2(dir.z, length(dir.xy))
            self.navigation.center = position
            self.navigation.distance = length(dir)
        elif isinstance(self.navigation, Orbit):
            focal = self.orient * fvec3(0, 0, 1)
            self.navigation.orient = quat(dir, focal) * self.navigation.orient
            self.navigation.center = position
            self.navigation.distance = length(dir)
        else:
            raise TypeError("navigation {} is not supported by 'look'".format(type(self.navigation)))

    def adjust(self, box:Box=None):
        ''' Make the navigation camera large enough to get the given box in .
            This is changing the zoom level
        '''
        if not box:    box = self.scene.box()
        if box.isempty():    return

        # get the most distant point to the focal axis
        invview = affineInverse(self.navigation.matrix())
        camera, look = fvec3(invview[3]), fvec3(invview[2])
        dist = length(noproject(box.center - camera, look)) + max(glm.abs(box.width)) / 2 * 1.1
        if not dist > 1e-6:
            return

        # adjust navigation distance
        if isinstance(self.projection, Perspective):
            self.navigation.distance = dist / tan(self.projection.fov / 2)
        elif isinstance(self.projection, Orthographic):
            self.navigation.distance = dist / self.projection.size
        else:
            raise TypeError('projection {} not supported'.format(type(self.projection)))

    def center(self, center: fvec3=None):
        ''' Relocate the navigation to the given position .
            This is translating the camera.
        '''
        if not center:
            center = self.scene.box().center
        if not isfinite(center):
            return

        self.navigation.center = center

def displayable(obj):
    ''' Return True if the given object has the matching signature to be added to a Scene '''
    return (
        type(obj) in overrides or 
        hasattr(obj, 'display') and
        callable(obj.display) and
        not isinstance(obj, type)
    )


try:
    from ..qt import *
except ImportError:
    pass
else:
    def navigation_tool(dispatcher, view):
        ''' Internal navigation tool '''    
        ctrl = alt = slow = False
        nav = curr = None
        moving = False
        hastouched = False
        while True:
            evt = yield
            evt.ignore()    # ignore the keys to pass shortcuts to parents
            
            if isinstance(evt, QKeyEvent):
                k = evt.key()
                press = evt.type() == QAllEvents.KeyPress
                if   k == QKeys.Key_Control:    ctrl = press
                elif k == QKeys.Key_Alt:        alt = press
                elif k == QKeys.Key_Shift:      slow = press
                if ctrl and alt:             curr = 'zoom'
                elif ctrl:                   curr = 'pan'
                elif alt:                    curr = 'rotate'
                else:                        curr = None
                # no accept because the shortcuts need to get the keys also

            elif evt.type() == QAllEvents.MouseButtonPress:
                last = evt.pos()
                if evt.button() == QMouseButton.MiddleButton:
                    nav = 'rotate'
                else:
                    nav = curr
                # prevent any scene interaction
                if nav:
                    evt.accept()

            elif evt.type() == QAllEvents.MouseMove:
                if nav:
                    moving = True
                    gap = evt.pos() - last
                    dx = gap.x() / view.height()
                    dy = gap.y() / view.height()
                    if nav == 'pan':         view.navigation.pan(dx, dy)
                    elif nav == 'rotate':    view.navigation.rotate(dx, dy, 0)
                    elif nav == 'zoom':        
                        middle = QPoint(view.width(), view.height())/2
                        f = ((last - middle).manhattanLength() / (evt.pos() - middle).manhattanLength())
                        view.navigation.zoom(f)
                    last = evt.pos()
                    view.update()
                    evt.accept()

            elif evt.type() == QAllEvents.MouseButtonRelease:
                if moving:
                    moving = False
                    evt.accept()

            elif evt.type() == QAllEvents.Wheel:
                view.navigation.zoom(exp(-evt.angleDelta().y() / (8 * 90)))    # the 8 factor is there because of the Qt documentation
                view.update()
                evt.accept()
        
            elif isinstance(evt, QTouchEvent):
                nav = None
                pts = evt.touchPoints()
                # view rotation
                if len(pts) == 2:
                    startlength = (pts[0].lastPos() - pts[1].lastPos()).manhattanLength()
                    zoom = startlength / (pts[0].pos() - pts[1].pos()).manhattanLength()
                    displt = ((pts[0].pos() + pts[1].pos()) / 2 - (pts[0].lastPos() + pts[1].lastPos()) / 2) / view.height()
                    dc = pts[0].pos() - pts[1].pos()
                    dl = pts[0].lastPos() - pts[1].lastPos()
                    rot = atan2(dc.y(), dc.x()) - atan2(dl.y(), dl.x())
                    view.navigation.zoom(zoom)
                    view.navigation.rotate(displt.x(), displt.y(), rot)
                    hastouched = True
                    view.update()
                    evt.accept()

                # view translation
                elif len(pts) == 3:
                    lc = (
                        pts[0].lastPos() +
                        pts[1].lastPos() +
                        pts[2].lastPos()
                    ) / 3
                    lr = (
                        (pts[0].lastPos() - lc).manhattanLength() +
                        (pts[1].lastPos() - lc).manhattanLength() +
                        (pts[2].lastPos() - lc).manhattanLength()
                    ) / 3
                    cc = (
                        pts[0].pos() +
                        pts[1].pos() +
                        pts[2].pos() 
                    ) / 3
                    cr = (
                        (pts[0].pos() - cc).manhattanLength() +
                        (pts[1].pos() - cc).manhattanLength() +
                        (pts[2].pos() - cc).manhattanLength()
                    ) / 3
                    zoom = lr / cr
                    displt = (cc - lc) / view.height()
                    view.navigation.zoom(zoom)
                    view.navigation.pan(displt.x(), displt.y())
                    hastouched = True
                    view.update()
                    evt.accept()

                # finish a gesture
                elif evt.type() in (QAllEvents.TouchEnd, QAllEvents.TouchUpdate):
                    evt.accept()

    class Turntable:
        ''' Navigation rotating on yaw and pitch around a center 
        
            Object used as `View.navigation`
        '''
        def __init__(self, center:fvec3=0, distance:float=1, yaw:float=0, pitch:float=0):
            self.center = fvec3(center)
            self.yaw = yaw
            self.pitch = pitch
            self.distance = distance
            self.tool = navigation_tool
            
        def rotate(self, dx, dy, dz):
            self.yaw += dx * pi
            self.pitch += dy * pi
            if self.pitch >  pi/2: self.pitch =  pi/2
            if self.pitch < -pi/2: self.pitch = -pi/2

        def pan(self, dx, dy):
            mat = transpose(mat3_cast(inverse(fquat(fvec3(pi/2 - self.pitch, 0, -self.yaw)))))
            self.center += (mat[0] * -dx + mat[1] * dy) * self.distance / 2

        def zoom(self, f):
            self.distance *= f
        
        def matrix(self) -> fmat4:
            # build rotation from view euler angles
            rot = inverse(fquat(fvec3(pi/2 - self.pitch, 0, -self.yaw)))
            mat = translate(mat4_cast(rot), -self.center)
            mat[3][2] -= self.distance
            return mat

    class Orbit:
        ''' Navigation rotating on the 3 axis around a center.
        
            Object used as `View.navigation`
        '''
        def __init__(self, center:fvec3=0, distance:float=1, orient:fvec3=fvec3(1,0,0)):
            self.center = fvec3(center)
            self.distance = float(distance)
            self.orient = fquat(orient)
            self.tool = navigation_tool
            
        def rotate(self, dx, dy, dz):
            # rotate from view euler angles
            self.orient = inverse(fquat(fvec3(-dy, -dx, dz) * pi)) * self.orient

        def pan(self, dx, dy):
            x, y, z = transpose(mat3_cast(self.orient))
            self.center += (fvec3(x) * -dx + fvec3(y) * dy) * self.distance / 2

        def zoom(self, f):
            self.distance *= f
        
        def matrix(self) -> fmat4:
            mat = translate(mat4_cast(self.orient), -self.center)
            mat[3][2] -= self.distance
            return mat

    class Perspective:
        ''' Object used as `View.projection` 
        
            Attributes:
                fov (float):    field of view (rad), defaulting to `settings.display['field_of_view']`
        '''
        def __init__(self, fov=None):
            self.fov = fov or settings.display['field_of_view']

        def matrix(self, ratio, distance) -> fmat4:
            return perspective(self.fov, ratio, distance*1e-2, distance*1e4)

    class Orthographic:
        ''' Object used as `View.projection` 
        
            Attributes:
                size (float):  

                    factor between the distance from camera to navigation center and the zone size to display
                    defaulting to `tan(settings.display['field_of_view']/2)`
        '''
        def __init__(self, size=None):
            self.size = size or tan(settings.display['field_of_view']/2)

        def matrix(self, ratio, distance) -> fmat4:
            return fmat4(
                1 / (ratio * distance * self.size),   0, 0, 0,
                0,       1 / (distance * self.size),     0, 0,
                0,       0, -2 / (distance * (1e3 - 1e-2)), 0,
                0,       0,   -(1e3 + 1e-2) / (1e3 - 1e-2), 1,
            )

    class QView3D(QOpenGLWidget):
        ''' Qt widget to render and interact with displayable objects.
            It holds a scene as renderpipeline.

            Attributes:

                scene:        the `Scene` object displayed
                projection:   `Perspective` or `Orthographic`
                navigation:   `Orbit` or `Turntable`
                tool:         list of callables in priority order to receive events

                targets:     render targets matching those requested in `scene.stacks`
                uniforms:    parameters for rendering, used in shaders
        '''
        def __init__(self, scene, projection=None, navigation=None, parent=None):
            # super init
            QOpenGLWidget.__init__(self, parent)
            CoreProfile = (
                QSurfaceFormat.OpenGLContextProfile.CoreProfile if QVersion == "PyQt6"
                else QSurfaceFormat.CoreProfile
            )
            StrongFocus = (
                Qt.FocusPolicy.StrongFocus if QVersion == "PyQt6"
                else Qt.StrongFocus
            )
            WA_AcceptTouchEvents = (
                Qt.WidgetAttribute.WA_AcceptTouchEvents if QVersion == "PyQt6"
                else Qt.WA_AcceptTouchEvents
            )
            fmt = QSurfaceFormat()
            fmt.setVersion(*opengl_version)
            fmt.setProfile(CoreProfile)
            fmt.setSamples(4)
            self.setFormat(fmt)
            
            # ugly trick to receive interaction events in a different function 
            # than QOpenGLWidget.event (that one is locking the GIL during the 
            # whole rendering, killing any possibility of having a computing thread 
            # aside) that event reception should be in the current widget ...
            self.handler = GhostWidget(self)
            self.handler.setFocusPolicy(StrongFocus)
            self.handler.setAttribute(WA_AcceptTouchEvents, True)
            self.setFocusProxy(self.handler)

            self.scene = scene if isinstance(scene, Scene3D) else Scene3D(scene)
            self.uniforms = {'proj':fmat4(1), 'view':fmat4(1), 'projview':fmat4(1)}    # last frame rendering constants
            self.targets = []
            self.steps = []
            self.step = 0
            self.stepi = 0

            # dump targets
            self.map_depth = None
            self.map_idents = None
            self.fresh = set()    # set of refreshed internal variables since the last render


            self.projection = projection or globals()[settings.scene['projection']]()
            self.navigation = navigation or globals()[settings.controls['navigation']]()

            self.tool = [Tool(self.navigation.tool, self)] # tool stack, the last tool is used for input events, until it is removed 

        def init(self):
            w, h = self.width(), self.height()

            ctx = self.scene.ctx
            assert ctx, 'context is not initialized'

            # self.fb_screen is already created and sized by Qt
            self.fb_screen = ctx.detect_framebuffer(self.defaultFramebufferObject())
            self.fb_ident = ctx.simple_framebuffer((w, h), components=3, dtype='f1')
            self.targets = [ ('screen', self.fb_screen, self.setup_screen),
                             ('ident', self.fb_ident, self.setup_ident)]
            self.map_ident = np.empty((h,w), dtype='u2')
            self.map_depth = np.empty((h,w), dtype='f4')

        def render(self):
            # set the opengl current context from Qt (doing it only from moderngl interferes with Qt)
            self.makeCurrent()
            w, h = self.fb_screen.size
            self.uniforms['view'] = view = self.navigation.matrix()
            self.uniforms['proj'] = proj = self.projection.matrix(w/h, self.navigation.distance)
            self.uniforms['projview'] = proj * view
            self.fresh.clear()

            # call the render stack
            self.scene.render(self)

        def preload(self):
            ''' Internal method to load common resources '''
            ctx, resources = self.scene.ctx, self.scene.resources
            resources['shader_ident'] = ctx.program(
                vertex_shader=open(resourcedir+'/shaders/object-ident.vert').read(),
                fragment_shader=open(resourcedir+'/shaders/ident.frag').read(),
            )

            resources['shader_subident'] = ctx.program(
                vertex_shader=open(resourcedir+'/shaders/object-item-ident.vert').read(),
                fragment_shader=open(resourcedir+'/shaders/ident.frag').read(),
            )

        def identstep(self, nidents):
            ''' Updates the amount of rendered idents and return the start ident for the calling rendering pass?
                Method to call during a renderstep
            '''
            s = self.step
            self.step += nidents
            self.steps[self.stepi] = self.step-1
            self.stepi += 1
            return s

        def refreshmaps(self):
            ''' Load the rendered frames from the GPU to the CPU
                - When a picture is used to GPU rendering it's called 'frame'
                - When it is dumped to the RAM we call it 'map' in this library
            '''
            if 'fb_ident' not in self.fresh:
                self.makeCurrent()    # set the scene context as current opengl context
                with self.scene.ctx as ctx:
                    #ctx.finish()
                    self.fb_ident.read_into(self.map_ident, viewport=self.fb_ident.viewport, components=2)
                    self.fb_ident.read_into(self.map_depth, viewport=self.fb_ident.viewport, components=1, attachment=-1, dtype='f4')
                self.fresh.add('fb_ident')

        # -- view stuff --

        def look(self, position: fvec3=None):
            if not position:    position = self.scene.box().center
            dir = position - fvec3(affineInverse(self.navigation.matrix())[3])
            if not dot(dir,dir) > 1e-6 or not isfinite(position):    return

            if isinstance(self.navigation, Turntable):
                self.navigation.yaw = atan2(dir.x, dir.y)
                self.navigation.pitch = -atan2(dir.z, length(dir.xy))
                self.navigation.center = position
                self.navigation.distance = length(dir)
            elif isinstance(self.navigation, Orbit):
                focal = self.orient * fvec3(0,0,1)
                self.navigation.orient = quat(dir, focal) * self.navigation.orient
                self.navigation.center = position
                self.navigation.distance = length(dir)
            else:
                raise TypeError("navigation {} is not supported by 'look'".format(type(self.navigation)))
            self.update()

        def adjust(self, box:Box=None):
            if not box:    box = self.scene.box()
            if box.isempty():    return

            # get the most distant point to the focal axis
            invview = affineInverse(self.navigation.matrix())
            camera, look = fvec3(invview[3]), fvec3(invview[2])
            dist = length(noproject(box.center-camera, look)) + max(glm.abs(box.width))/2 * 1.1
            if not dist > 1e-6:    return

            # adjust navigation distance
            if isinstance(self.projection, Perspective):
                self.navigation.distance = dist / tan(self.projection.fov/2)
            elif isinstance(self.projection, Orthographic):
                self.navigation.distance = dist / self.projection.size
            else:
                raise TypeError('projection {} not supported'.format(type(self.projection)))
            self.update()

        def center(self, center: fvec3=None):
            if not center:    center = self.scene.box().center
            if not isfinite(center):    return

            self.navigation.center = center
            self.update()

        # TODO : QPoint to vec2
        def somenear(self, point: QPoint, radius=None) -> QPoint:
            ''' Return the closest coordinate to coords, (within the given radius) for which there is an object at
                So if objnear is returning something, objat and ptat will return something at the returned point
            '''
            if radius is None:
                radius = settings.controls['snap_dist']
            self.refreshmaps()
            for x, y in snailaround(qt_to_glm(point), (self.map_ident.shape[1], self.map_ident.shape[0]), radius):
                ident = int(self.map_ident[-y, x])
                if ident:
                    return QPoint(x, y)

        def ptat(self, point: QPoint) -> fvec3:
            ''' Return the point of the rendered surfaces that match the given window coordinates '''
            self.refreshmaps()
            viewport = self.fb_ident.viewport
            depthred = float(self.map_depth[-point.y,point.x])
            x =  (point.x/viewport[2] *2 -1)
            y = -(point.y/viewport[3] *2 -1)

            if depthred == 1.0:
                return None
            else:
                view = self.uniforms['view']
                proj = self.uniforms['proj']
                a,b = proj[2][2], proj[3][2]
                depth = b/(depthred + a) * 0.5    # TODO get the true depth  (can't get why there is a strange factor ... opengl trick)
                #near, far = self.projection.limits  or settings.display['view_limits']
                #depth = 2 * near / (far + near - depthred * (far - near))
                #print('depth', depth, depthred)
                return vec3(fvec3(affineInverse(view) * fvec4(
                            depth * x /proj[0][0],
                            depth * y /proj[1][1],
                            -depth,
                            1)))

        def ptfrom(self, point: QPoint, center: fvec3) -> fvec3:
            ''' 3D point below the cursor in the plane orthogonal to the sight, with center as origin '''
            view = self.uniforms['view']
            proj = self.uniforms['proj']
            viewport = self.fb_ident.viewport
            x =  (point.x/viewport[2] *2 -1)
            y = -(point.y/viewport[3] *2 -1)
            depth = (view * fvec4(fvec3(center),1))[2]
            return vec3(fvec3(affineInverse(view) * fvec4(
                        -depth * x /proj[0][0],
                        -depth * y /proj[1][1],
                        depth,
                        1)))


        def itemat(self, point: QPoint) -> 'key':
            ''' Return the key path of the object at the given screen position (widget relative).
                If no object is at this exact location, None is returned
            '''
            self.refreshmaps()
            point = uvec2(qt_to_glm(point))
            ident = int(self.map_ident[-point.y, point.x])
            if ident and 'ident' in self.scene.stacks:
                rdri = bisect(self.steps, ident)
                if rdri == len(self.steps):
                    print('internal error: object ident points out of idents list')
                while rdri > 0 and self.steps[rdri-1] == ident:    rdri -= 1
                if rdri > 0:    subi = ident - self.steps[rdri-1] - 1
                else:            subi = ident - 1
                
                if rdri >= len(self.scene.stacks['ident']):
                    print('wrong identification index', ident, self.scene.stacks['ident'][-1])
                    nprint(self.scene.stacks['ident'])
                    return
                
                return (*self.scene.stacks['ident'][rdri][0], subi)

        def setup_ident(self):
            # steps for fast fast search of displays with the idents
            self.stepi = 0
            self.step = 1
            if 'ident' in self.scene.stacks and len(self.scene.stacks['ident']) != len(self.steps):
                self.steps = [0] * len(self.scene.stacks['ident'])
            # ident rendering setup
            ctx = self.scene.ctx
            ctx.multisample = False
            ctx.enable_only(mgl.DEPTH_TEST)
            ctx.blend_func = mgl.ONE, mgl.ZERO
            ctx.blend_equation = mgl.FUNC_ADD
            self.target.clear(0)

        def setup_screen(self):
            # screen rendering setup
            ctx = self.scene.ctx
            ctx.multisample = True
            ctx.enable_only(mgl.BLEND | mgl.DEPTH_TEST)
            ctx.blend_func = mgl.SRC_ALPHA, mgl.ONE_MINUS_SRC_ALPHA
            ctx.blend_equation = mgl.FUNC_ADD
            
            background = settings.display['background_color']
            if len(background) == 3:
                self.target.clear(*background, alpha=1)
            elif len(background) == 4:
                self.target.clear(*background)
            else:
                raise ValueError(f"background_color must be a RGB or RGBA tuple, currently {background}")


        # -- event system --

        def inputEvent(self, evt):
            ''' Default handler for every input event (mouse move, press, release, keyboard, ...)
                When the event is not accepted, the usual matching Qt handlers are used (mousePressEvent, KeyPressEvent, etc).

                This function can be overwritten to change the view widget behavior.
            '''
            # send the event to the current tools using the view
            if self.tool:
                for tool in reversed(self.tool):
                    tool(evt)
                    if evt.isAccepted():    return

            # send the event to the scene objects, descending the item tree
            if isinstance(evt, QMouseEvent) and evt.type() in (
                QAllEvents.MouseButtonPress,
                QAllEvents.MouseButtonRelease,
                QAllEvents.MouseButtonDblClick,
                QAllEvents.MouseMove
            ):
                pos = self.somenear(evt.pos())
                if pos:
                    key = self.itemat(pos)
                    if key:
                        self.control(key, evt)
                        if evt.isAccepted():    return

                # if clicks are not accepted, then some following keyboard events may not come to the widget
                # NOTE this also discarding the ability to move the window from empty areas
                if evt.type() == QAllEvents.MouseButtonPress:
                    evt.accept()

        def control(self, key, evt):
            ''' Transmit a control event successively to all the displays matching the key path stages.
                At each level, if the event is not accepted, it transmits to sub items

                This function can be overwritten to change the interaction with the scene objects.
            '''
            disp = self.scene.displays
            stack = []
            for i in range(1,len(key)):
                disp = disp[key[i-1]]
                disp.control(self, key[:i], key[i:], evt)
                if evt.isAccepted(): return
                stack.append(disp)

            if evt.type() == QAllEvents.MouseButtonPress and evt.button() == QMouseButton.LeftButton:
                disp = stack[-1]
                # select what is under cursor
                if type(disp).__name__ in ('MeshDisplay', 'WebDisplay'):
                    disp.vertices.selectsub(key[-1])
                    disp.selected = any(disp.vertices.flags & 0x1)
                else:
                    disp.selected = not disp.selected
                # make sure that a display is selected if one of its sub displays is
                for disp in reversed(stack):
                    if hasattr(disp, '__iter__'):
                        disp.selected = any(sub.selected for sub in disp)
                self.update()

        # -- Qt things --

        def initializeGL(self):
            # retrieve global shared context if available
            global global_context_3D

            if QApplication.testAttribute(AA_ShareOpenGLContexts):
                if not global_context_3D:
                    global_context_3D = mgl.create_context()
                self.scene.ctx = global_context_3D
            # or create a context
            else:
                self.scene.ctx = mgl.create_context()
            self.init()
            self.preload()

        def paintGL(self):
            self.makeCurrent()
            self.render()

        def resizeEvent(self, evt):
            QOpenGLWidget.resizeEvent(self, evt)
            self.handler.resize(self.size())
            self.init()
            self.update()

        def changeEvent(self, evt):
            # detect theme change
            if evt.type() == QAllEvents.PaletteChange and settings.display['system_theme']:
                settings.use_qt_colors()
            return QOpenGLWidget.changeEvent(self, evt)


    class SubView3D(SubView):
        ''' Qt widget to render and interact with displayable objects.
            It holds a scene as renderpipeline.

            Attributes:

                scene:        the `Scene` object displayed
                projection:   `Perspective` or `Orthographic`
                navigation:   `Orbit` or `Turntable`
                tool:         list of callables in priority order to receive events

                targets:     render targets matching those requested in `scene.stacks`
                uniforms:    parameters for rendering, used in shaders
        '''
        def __init__(self, scene, projection=None, navigation=None, parent=None):
            super().__init__(self, scene, projection=projection, navigation=navigation)

        def look(self, position: fvec3=None):
            """
            Make the scene navigation look at the position. 
            This is changing the camera direction, center and distance
            """
            super().look(self, position)

        def adjust(self, box:Box=None):
            """
            Make the navigation camera large enough to get the given box in.
            This is changing the zoom level
            """
            super().adjust(self, box)

        def center(self, center: fvec3=None):
            """
            Relocate the navigation to the given position.
            This is translating the camera
            """
            super().center(self, center)

        # TODO : implement stack method (see Group.stack)
        # Options :
        # 1. Make the Subview render in its buffer then render to the main scene
        # 2. Isolate objects by changing the uniform attribute and restore them in the main render
        def stack(self, scene):
            """
            Not yet implemented
            """
            for key,display in self.displays.items():
                for sub, target, priority, func in display.stack(scene):
                    yield ((key, *sub), target, priority, func)
        
        def control(self, key, evt):
            ''' Transmit a control event successively to all the displays matching the key path stages.
                At each level, if the event is not accepted, it transmits to sub items

                This function can be overwritten to change the interaction with the scene objects.
            '''
            disp = self.scene.displays
            stack = []
            for i in range(1,len(key)):
                disp = disp[key[i-1]]
                disp.control(self, key[:i], key[i:], evt)
                if evt.isAccepted(): return
                stack.append(disp)

            if evt.type() == QAllEvents.MouseButtonPress and evt.button() == QMouseButton.LeftButton:
                disp = stack[-1]
                # select what is under cursor
                if type(disp).__name__ in ('SolidDisplay', 'WebDisplay'):
                    disp.vertices.selectsub(key[-1])
                    disp.selected = any(disp.vertices.flags & 0x1)
                else:
                    disp.selected = not disp.selected
                # make sure that a display is selected if one of its sub displays is
                for disp in reversed(stack):
                    if hasattr(disp, '__iter__'):
                        disp.selected = any(sub.selected    for sub in disp)
                self.update()

    class GhostWidget(QWidget):
        def __init__(self, parent):
            super().__init__(parent)

        def event(self, evt):
            if isinstance(evt, QInputEvent):
                # set the opengl current context from Qt (doing it only from moderngl interferes with Qt)
                #self.makeCurrent()
                evt.ignore()
                self.parent().inputEvent(evt)
                if evt.isAccepted():    return True
            elif isinstance(evt, QFocusEvent):
                self.parent().event(evt)
            return super().event(evt)
