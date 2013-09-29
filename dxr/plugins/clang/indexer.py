import csv, cgi
import json
import dxr.plugins
import dxr.schema
import os, sys
import glob
import re, urllib
from dxr.languages import language_schema


PLUGIN_NAME   = 'clang'


incremental = False
def pre_process(tree, env):
    global incremental
    incremental = tree.incremental
    # Setup environment variables for inspecting clang as runtime
    # We'll store all the havested metadata in the plugins temporary folder.
    temp_folder   = os.path.join(tree.temp_folder, PLUGIN_NAME)
    indexer_dir = os.path.dirname(sys.modules['dxr.plugins.clang.indexer'].__file__)
    flags = [
        '-load', os.path.join(indexer_dir, 'libclang-index-plugin.so'),
        '-add-plugin', 'dxr-index',
        '-plugin-arg-dxr-index', tree.source_folder
    ]
    flags_str = ""
    for flag in flags:
        flags_str += ' -Xclang ' + flag
    flags_str += ' -Qunused-arguments '
    env['DXR_CXX_CLANG_OBJECT_FOLDER']  = tree.object_folder
    env['DXR_CXX_CLANG_TEMP_FOLDER']    = os.path.join(tree.temp_folder,'clang')
    for cc in 'cc','gcc','clang':
        fn = os.path.join(tree.bin_folder,cc)
        with open(fn, 'w') as f:
            f.write('#!/bin/bash\n')
            f.write('PATH=%s\n' % env['PATH'])
            f.write('export DXR_CXX_CLANG_OBJECT_FOLDER=%s\n' % env['DXR_CXX_CLANG_OBJECT_FOLDER'])
            f.write('export DXR_CXX_CLANG_TEMP_FOLDER=%s\n' % env['DXR_CXX_CLANG_TEMP_FOLDER'])
            f.write('exec clang %s "$@"\n' % flags_str)
        os.chmod(fn, 0700)
    for cc in 'c++','g++','clang++':
        fn = os.path.join(tree.bin_folder,cc)
        with open(fn, 'w') as f:
            f.write('#!/bin/bash\n')
            f.write('PATH=%s\n' % env['PATH'])
            f.write('export DXR_CXX_CLANG_OBJECT_FOLDER=%s\n' % env['DXR_CXX_CLANG_OBJECT_FOLDER'])
            f.write('export DXR_CXX_CLANG_TEMP_FOLDER=%s\n' % env['DXR_CXX_CLANG_TEMP_FOLDER'])
            f.write('exec clang++ %s "$@"\n' % flags_str)
        os.chmod(fn, 0700)
    env['PATH'] = tree.bin_folder+os.pathsep + env['PATH']


def post_process(tree, conn):
    global incremental
    incremental = tree.incremental
    print "cxx-clang post-processing:"; sys.stdout.flush()
    if not tree.incremental:
        print " - Adding tables"; sys.stdout.flush()
        conn.executescript(schema.get_create_sql())

        for t in 'functions','variables','typedefs','macros','types','scopes':
            conn.execute('CREATE INDEX %s on %s(name)' % (t+'_name_index', t))

        conn.execute('DROP TABLE IF EXISTS max_id')
        conn.execute('CREATE TABLE max_id (kind TEXT UNIQUE, id INTEGER)')
    else:
        read_files(conn)

    print " - Processing files"; sys.stdout.flush()
    temp_folder = os.path.join(tree.temp_folder, PLUGIN_NAME)
    for f in glob.iglob(os.path.join(temp_folder, '*.csv.gz')):
        dump_indexer_output(conn, f)
        os.remove(f)

    conn.commit()
    conn.execute('CREATE TABLE impl_tmp (file_id INTEGER, file_line INTEGER, file_col INTEGER,' \
                 'base_file_id INTEGER, base_file_line INTEGER, base_file_col INTEGER, access VARCHAR(32))')
    conn.execute('INSERT INTO impl_tmp SELECT DISTINCT * FROM impl')
    conn.execute('DROP TABLE impl')
    conn.execute('ALTER TABLE impl_tmp RENAME TO impl')
    conn.commit()
    conn.execute('CREATE INDEX impl_file_index ON impl(file_id,file_line,file_col)')
    conn.execute('CREATE INDEX impl_base_file_index ON impl(base_file_id,base_file_line,base_file_col)')
    conn.commit()

def db_fixup(conn):
    fixup_scope(conn)

    print " - Generating inheritance graph"; sys.stdout.flush()
    generate_inheritance(conn)

    print " - Updating definitions"; sys.stdout.flush()
    update_defids(conn)

    print " - Updating references"; sys.stdout.flush()
    update_refs(conn)

    print " - Committing changes"; sys.stdout.flush()
    conn.commit()



schema = dxr.schema.Schema({
    # Typedef information in the tables
    "typedefs": [
        ("_location", True, 'scope'),
        ("name", "VARCHAR(256)", False),       # Simple name of the typedef
        ("qualname", "VARCHAR(256)", False),   # Fully-qualified name of the typedef
        ("modifiers", "VARCHAR(256)", True),  # Modifiers (e.g., private)
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True, 'decl'),
        ("_index", "qualname"),
    ],
    # Namespaces
    "namespaces": [
        ("name", "VARCHAR(256)", False),       # Simple name of the namespace
        ("qualname", "VARCHAR(256)", False),   # Fully-qualified name of the namespace
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True, 'decl'),
        ("_index", "qualname"),
    ],
    # References to namespaces
    "namespace_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("qualname", "VARCHAR(256)", False),
        ("_location", True),
    ],
    # Namespace aliases
    "namespace_aliases": [
        ("name", "VARCHAR(256)", False),       # Simple name of the namespace alias
        ("qualname", "VARCHAR(256)", False),   # Fully-qualified name of the namespace alias
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_location", True),
        ("_location", True, 'decl'),
        ("_index", "qualname"),
    ],
    # References to namespace aliases
    "namespace_alias_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("qualname", "VARCHAR(256)", False),   # Fully-qualified name of the namespace alias
        ("_location", True),
    ],
    # References to functions
    "function_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
        ("_location", True, 'decl'),
        ("qualname", "VARCHAR(256)", True),
    ],
    # References to macros
    "macro_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
        ("_location", True, 'decl'),
    ],
    # References to types
    "type_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
        ("_location", True, 'decl'),
        ("qualname", "VARCHAR(256)", True),
    ],
    # References to typedefs
    "typedef_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
        ("_location", True, 'decl'),
        ("qualname", "VARCHAR(256)", True),
    ],
    # References to variables
    "variable_refs": [
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
        ("_location", True, 'decl'),
        ("qualname", "VARCHAR(256)", True),
    ],
    # Warnings found while compiling
    "warnings": [
        ("msg", "VARCHAR(256)", False), # Text of the warning
        ("opt", "VARCHAR(64)", True),   # option controlling this warning (-Wxxx)
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True),
    ],
    # Declaration/definition mapping for functions
    "function_decldef": [
        ("_ulocation", True),
        # Extents of the declaration
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
    ],
    # Declaration/definition mapping for types
    "type_decldef": [
        ("_ulocation", True),
        # Extents of the declaration
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
    ],
    # Declaration/definition mapping for variables
    "variable_decldef": [
        ("_ulocation", True),
        # Extents of the declaration
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
    ],
    # Macros: this is a table of all of the macros we come across in the code.
    "macros": [
        ("name", "VARCHAR(256)", False), # The name of the macro
        ("args", "VARCHAR(256)", True),  # The args of the macro (if any)
        ("text", "TEXT", True),          # The macro contents
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
        ("_ulocation", True, 'decl'),
    ],
    # includes: this is a table of all of the includes we process
    "includes": [
        ("inc", "INTEGER", True), # The file that's been included
        ("_ulocation", True),
        ("extent_start", "INTEGER", True),
        ("extent_end", "INTEGER", True),
    ],
})


file_cache = {}
file_cache_inv = {}
decl_master = {}
inheritance = {}
calls = {}
overrides = {}

def read_files(conn):
    global file_cache
    global file_cache_inv

    for row in conn.execute("SELECT id,path FROM files"):
        file_cache[row[1]] = row[0]
        file_cache_inv[int(row[0])] = row[1]

def getFileID(conn, path):
    global file_cache

    file_id = file_cache.get(path, False)

    if file_id is not False:
        return file_id

    cur = conn.cursor()
    row = cur.execute("SELECT id FROM files where path=?", (path,)).fetchone()
    file_id = None
    if row:
        file_id = row[0]
    else:
        if path[0] == '/':
            return None
        if path[0] == '<':
            return None
        if path.startswith('--GENERATED--'):
            return None
        cur.execute("INSERT INTO files (path) VALUES (?)", (path,))
        row = cur.execute("SELECT id from files where path=?", (path,)).fetchone()
        if row:
            file_id = row[0]
        else:
            sys.exit(1)
    file_cache[path] = file_id
    return file_id

processed={}
def clean(file_id, conn):
    global incremental
    global processed
    if not incremental:
        return
    if file_id in processed:
        return

    global file_cache_inv

    processed[file_id] = True
    cur = conn.cursor()
    for kind in ['function','variable','type']:
        cur.execute('DELETE FROM '+kind+'s WHERE file_id=?',(file_id,))
        cur.execute('DELETE FROM '+kind+'_decldef WHERE file_id=?',(file_id,))
    for kind in ['typedef','namespace','macro']:
        cur.execute('DELETE FROM '+kind+'s WHERE decl_file_id=?',(file_id,))
    for kind in ['include','warning','scope']:
        cur.execute('DELETE FROM '+kind+'s WHERE file_id=?',(file_id,))

    for kind in ['function','macro','namespace','type','typedef','variable']:
        cur.execute('DELETE FROM '+kind+'_refs WHERE file_id=?',(file_id,))

    for kind in ['alias_refs','aliases']:
        cur.execute('DELETE FROM namespace_'+kind+' WHERE file_id=?',(file_id,))

def splitLoc(conn, value):
    arr = value.split(':')
    return (getFileID(conn, arr[0]), int(arr[1]), int(arr[2]))

def fixupEntryPath(args, file_key, conn, prefix=None):
    value = args[file_key]
    loc = splitLoc(conn, value)

    if prefix is not None:
        prefix = prefix + "_"
    else:
        prefix = ''

    args[prefix + 'file_id'] = loc[0]
    args[prefix + 'file_line'] = loc[1]
    args[prefix + 'file_col'] = loc[2]
    return loc[0] is not None

def fixupExtent(args, extents_key):
    if extents_key not in args:
        return

    value = args[extents_key]
    arr = value.split(':')

    args['extent_start'] = int(arr[0])
    args['extent_end'] = int(arr[1])
    del args[extents_key]

def getScope(args, conn):
    row = conn.execute("SELECT file_id FROM scopes WHERE file_id=? AND file_line=? AND file_col=?",
                                          (args['file_id'], args['file_line'], args['file_col'])).fetchone()

    if row is not None:
        return row[0]

    return None

def addScope(args, conn, name):
    scope = {}
    scope['name'] = args[name]
    scope['file_id'] = args['file_id']
    scope['file_line'] = args['file_line']
    scope['file_col'] = args['file_col']
    scope['language'] = 'native'

    stmt = language_schema.get_insert_sql('scopes', scope)
    conn.execute(stmt[0], stmt[1])

def handleScope(args, conn, canonicalize=False):
    scope = {}

    if 'scopename' not in args:
        return

    scope['name'] = args['scopename']
    scope['loc'] = args['scopeloc']
    scope['language'] = 'native'
    if not fixupEntryPath(scope, 'loc', conn):
        return None

    if canonicalize is True:
        decl = canonicalize_decl(scope['name'], scope['file_id'], scope['file_line'], scope['file_col'])
        scope['file_id'], scope['file_line'], scope['file_col'] = decl[1], decl[2], decl[3]

    scopeid = getScope(scope, conn)

    if scopeid is None:
        stmt = language_schema.get_insert_sql('scopes', scope)
        conn.execute(stmt[0], stmt[1])

    if scopeid is not None:
        args['scope_file_id'], args['scope_file_line'], args['scope_file_col'] = scope['file_id'], scope['file_line'], scope['file_col']

def process_decldef(args, conn):
    if 'kind' not in args:
        return None

    declloc = args['declloc']
    declid, declline, declcol = splitLoc (conn, declloc)
    if declid is None:
        return None

    clean(declid, conn)

    if not fixupEntryPath(args, 'declloc', conn):
        return None
    fixupExtent(args, 'extent')
    
    return schema.get_insert_sql(args['kind'] + '_decldef', args)

def process_type(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None
    if not fixupEntryPath(args, 'declloc', conn, 'decl'):
        return None

    clean(args['file_id'], conn)

    # Scope might have been previously added to satisfy other process_* call
    scopeid = getScope(args, conn)

    if scopeid is None:
        addScope(args, conn, 'name')

    handleScope(args, conn)
    fixupExtent(args, 'extent')

    return language_schema.get_insert_sql('types', args)

def process_typedef(args, conn):
    if not fixupEntryPath(args, 'declloc', conn, 'decl'):
        return None

    clean(args['decl_file_id'], conn)

    fixupExtent(args, 'extent')
    handleScope(args, conn)
    return schema.get_insert_sql('typedefs', args)

def process_function(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None
    if not fixupEntryPath(args, 'declloc', conn, 'decl'):
        return None

    clean(args['file_id'], conn)

    scopeid = getScope(args, conn)

    if scopeid is None:
        args['id'] = scopeid
        addScope(args, conn, 'name')

    if 'override' in args:
        fixupEntryPath(args, 'override', conn, 'override')

    handleScope(args, conn)
    fixupExtent(args, 'extent')
    return language_schema.get_insert_sql('functions', args)

def process_impl(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None
    if not fixupEntryPath(args, 'base', conn, 'base'):
        return None

    clean(args['file_id'], conn)

    return language_schema.get_insert_sql('impl', args)

def process_variable(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None
    if not fixupEntryPath(args, 'declloc', conn, 'decl'):
        return None

    clean(args['file_id'], conn)

    handleScope(args, conn)
    fixupExtent(args, 'extent')
    return language_schema.get_insert_sql('variables', args)

def process_ref(args, conn):
    if 'extent' not in args:
        return None
    if 'kind' not in args:
        return None

    if not fixupEntryPath(args, 'loc', conn):
        return None
    if 'declloc' in args:
        fixupEntryPath(args, 'declloc', conn, 'decl')

    clean(args['file_id'], conn)

    fixupExtent(args, 'extent')

    return schema.get_insert_sql(args['kind'] + '_refs', args)

def process_warning(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None

    clean(args['file_id'], conn)

    fixupExtent(args, 'extent')
    return schema.get_insert_sql('warnings', args)

def process_include(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None
    args['inc'] = getFileID(conn, args['inc'])
    if not args['inc']:
        return None

    clean(args['file_id'], conn)

    fixupExtent(args, 'extent')
    return schema.get_insert_sql('includes', args)

def process_macro(args, conn):
    if 'text' in args:
        args['text'] = args['text'].replace("\\\n", "\n").strip()
    if not fixupEntryPath(args, 'declloc', conn, 'decl'):
        return None

    clean(args['decl_file_id'], conn)

    fixupExtent(args, 'extent')
    return schema.get_insert_sql('macros', args)

def process_call(args, conn):
    if 'callername' in args:
        calls[args['callername'], args['callerloc'],
                    args['calleename'], args['calleeloc']] = args
    else:
        calls[args['calleename'], args['calleeloc']] = args

    return None

def process_namespace(args, conn):
    if not fixupEntryPath(args, 'declloc', conn,'decl'):
        return None

    clean(args['decl_file_id'], conn)

    fixupExtent(args, 'extent')
    return schema.get_insert_sql('namespaces', args)

def process_namespace_alias(args, conn):
    if not fixupEntryPath(args, 'loc', conn):
        return None

    clean(args['file_id'], conn)

    fixupExtent(args, 'extent')
    return schema.get_insert_sql('namespace_aliases', args)

def load_indexer_output(fname):
    f = open(fname, "rb")
    try:
        parsed_iter = csv.reader(f)
        for line in parsed_iter:
            # Our first column is the type that we're reading, the others are just
            # an args array to be passed in
            argobj = {}
            for i in range(1, len(line), 2):
                argobj[line[i]] = line[i + 1]
            globals()['process_' + line[0]](argobj)
    except:
        print fname, line
        raise
    finally:
        f.close()

import gzip

def dump_indexer_output(conn, fname):
    f = gzip.open(fname, 'r')
    limit = 0

    try:
        parsed_iter = csv.reader(f)
        for line in parsed_iter:
            args = {}
            # Our first column is the type that we're reading, the others are just
            # a key/value pairs array to be passed in
            for i in range(1, len(line), 2):
                args[line[i]] = line[i + 1]

            stmt = globals()['process_' + line[0]](args, conn)

            if stmt is None:
                continue

            if isinstance(stmt, list):
                for elem in list:
                    conn.execute(elem[0], elem[1])
            elif isinstance(stmt, tuple):
                try:
                    conn.execute(stmt[0], stmt[1])
                except:
                    print line
                    print stmt
                    raise
            else:
                conn.execute(stmt)

            limit = limit + 1

            if limit > 10000:
                limit = 0
                conn.commit()
    except IndexError, e:
        raise e
    finally:
        f.close()

def canonicalize_decl(name, id, line, col):
    value = decl_master.get((name, id, line, col), None)

    if value is None:
        return (name, id, line, col)
    else:
        return (name, value[0], value[1], value[2])

def fixup_scope(conn):
    conn.execute ("UPDATE types SET scopeid = (SELECT id FROM scopes WHERE " +
                                "scopes.file_id = types.file_id AND scopes.file_line = types.file_line " +
                                "AND scopes.file_col = types.file_col) WHERE scopeid IS NULL")
    conn.execute ("UPDATE functions SET scopeid = (SELECT id from scopes where " +
                                "scopes.file_id = functions.file_id AND scopes.file_line = functions.file_line " +
                                "AND scopes.file_col = functions.file_col) WHERE scopeid IS NULL")
    conn.execute ("UPDATE variables SET scopeid = (SELECT id from scopes where " +
                                "scopes.file_id = variables.file_id AND scopes.file_line = variables.file_line " +
                                "AND scopes.file_col = variables.file_col) WHERE scopeid IS NULL")


def build_inherits(base, child, direct):
    db = { 'tbase': base, 'tderived': child }
    if direct is not None:
        db['inhtype'] = direct
    return db

def generate_inheritance(conn):
    childMap, parentMap = {}, {}
    types = {}

    for row in conn.execute("SELECT qualname, file_id, file_line, file_col, id from types").fetchall():
        types[(row[0], row[1], row[2], row[3])] = row[4]

    for infoKey in inheritance:
        info = inheritance[infoKey]
        try:
            base_loc = splitLoc(conn, info['tbloc'])
            child_loc = splitLoc(conn, info['tcloc'])
            if base_loc[0] is None or child_loc[0] is None:
                continue

            base = types[canonicalize_decl(info['tbname'], base_loc[0], base_loc[1], base_loc[2])]
            child = types[canonicalize_decl(info['tcname'], child_loc[0], child_loc[1], child_loc[2])]
        except KeyError:
            continue

        conn.execute("INSERT OR IGNORE INTO impl(tbase, tderived, inhtype, file_id, dile_line, file_col) VALUES (?, ?, ?, ?, ?, ?)",
                                  (base, child, info.get('access', ''),
                                   child_loc[0], child_loc[1], child_loc[2]))

        # Get all known relations
        subs = childMap.setdefault(child, [])
        supers = parentMap.setdefault(base, [])
        # Use this information
        for sub in subs:
            conn.execute("INSERT OR IGNORE INTO impl(tbase, tderived) VALUES (?, ?)",
                                      (base, sub))
            parentMap[sub].append(base)
        for sup in supers:
            conn.execute("INSERT OR IGNORE INTO impl(tbase, tderived) VALUES (?, ?)",
                                      (sup, child))
            childMap[sup].append(child)

        # Carry through these relations
        newsubs = childMap.setdefault(base, [])
        newsubs.append(child)
        newsubs.extend(subs)
        newsupers = parentMap.setdefault(child, [])
        newsupers.append(base)
        newsupers.extend(supers)


def update_defids(conn):
    sql = """
        UPDATE type_decldef SET defid = (
              SELECT id
                FROM types AS def
               WHERE def.file_id   = definition_file_id
                 AND def.file_line = definition_file_line
                 AND def.file_col  = definition_file_col
        )"""
    conn.execute(sql)
    sql = """
        UPDATE function_decldef SET defid = (
              SELECT id
                FROM functions AS def
               WHERE def.file_id   = definition_file_id
                 AND def.file_line = definition_file_line
                 AND def.file_col  = definition_file_col
        )"""
    conn.execute(sql)
    sql = """
        UPDATE variable_decldef SET defid = (
              SELECT id
                FROM variables AS def
               WHERE def.file_id   = definition_file_id
                 AND def.file_line = definition_file_line
                 AND def.file_col  = definition_file_col
        )"""
    conn.execute(sql)


def update_refs(conn):
    # References to declarations
    sql = """
        UPDATE type_refs SET refid = (
                SELECT defid
                  FROM type_decldef AS decl
                 WHERE decl.file_id   = referenced_file_id
                   AND decl.file_line = referenced_file_line
                   AND decl.file_col  = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE function_refs SET refid = (
                SELECT defid
                  FROM function_decldef AS decl
                 WHERE decl.file_id   = referenced_file_id
                   AND decl.file_line = referenced_file_line
                   AND decl.file_col  = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE variable_refs SET refid = (
                SELECT defid
                  FROM variable_decldef AS decl
                 WHERE decl.file_id   = referenced_file_id
                   AND decl.file_line = referenced_file_line
                   AND decl.file_col  = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)

    # References to definitions
    sql = """
        UPDATE macro_refs SET refid = (
                SELECT id
                  FROM macros AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE type_refs SET refid = (
                SELECT id
                  FROM types AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE typedef_refs SET refid = (
                SELECT id
                  FROM typedefs AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE function_refs SET refid = (
                SELECT id
                  FROM functions AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE variable_refs SET refid = (
                SELECT id
                  FROM variables AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE namespace_refs SET refid = (
                SELECT id
                  FROM namespaces AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
    sql = """
        UPDATE namespace_alias_refs SET refid = (
                SELECT id
                  FROM namespace_aliases AS def
                 WHERE def.file_id    = referenced_file_id
                   AND def.file_line  = referenced_file_line
                   AND def.file_col   = referenced_file_col
        ) WHERE refid IS NULL"""
    conn.execute(sql)
