#!/usr/bin/python
import sqlite3
import sys
import os.path

class index:
    def __init__(self,dbfile):
        self.dxr=sqlite3.connect(dbfile)
        self.dxr.row_factory = sqlite3.Row
        self.cursor = self.dxr.cursor()

    def find_file_id(self,path):
        i = self.cursor.execute('select id from files where path=?', (path,)).fetchall()
        if len(i) == 1:
            return i[0][0]
        return None

    def show_includes(self,id):
        sys.stdout.write('(include\n')
        for row in self.cursor.execute('SELECT path,extent_start,extent_end FROM includes,files WHERE file_id=? ' \
                                       'AND extent_start NOT NULL AND inc=id',
                                       (id,)):
            path = row['path']
            sys.stdout.write('  (%d %d "%s")\n' % (row['extent_start'], row['extent_end'], path))
        sys.stdout.write(')\n')

    def decoration(self,id):
        self.refs = {}
        self.decorate('function',id)
        self.decorate('variable',id)
        self.decorate('type',id)
        self.decorate('typedef',id)
        self.decorate('macro',id)

    def identify(self,id):
        kind,fid,line,col,name = id
        id = (kind,fid,line,col)
        if id in self.refs:
            return self.refs[id]

        if kind == 'function' or kind == 'variable':
            gettype = ',type'
        else:
            gettype = ''
        row = self.cursor.execute('SELECT decl_file_id,decl_file_line,decl_file_col,'+ \
                                  defn_name(kind)+gettype+' FROM '+kind+'s WHERE decl_file_id=? AND ' \
                                  'decl_file_line=? AND decl_file_col=?', \
                                  (fid,line,col)).fetchone()
        if not row:
            row = self.cursor.execute('SELECT file_id,file_line,file_col,'+ \
                                      defn_name(kind)+gettype+' FROM '+kind+'s WHERE file_id=? AND ' \
                                      'file_line=? AND file_col=?', \
                                      (fid,line,col)).fetchone()
        if not row and name:
            row = self.cursor.execute('SELECT decl_file_id,decl_file_line,decl_file_col'+gettype+ \
                                      ' FROM '+kind+'s WHERE '+defn_name(kind)+'=?',(name,)).fetchone()
        if row:
            if not name:
                name = row[3]
            if kind == 'function' or kind == 'variable':
                type = row['type']
            else:
                type = None
            self.refs[id] = (kind,row[0],row[1],row[2],name,type)
        else:
            self.refs[id] = None
        return self.refs[id]

    def decorate(self,kind,id):
        allthings = {}
        if kind == 'macro':
            getname=''
        else:
            getname=',qualname'
        things = {}
        if kind == 'function' or kind == 'variable' or kind == 'type':
            for row in self.cursor.execute('SELECT file_line,file_col,extent_start,extent_end ' \
                                           'FROM '+kind+'_decldef WHERE file_id=? AND extent_start NOT NULL', (id,)):
                line, col = row['file_line'],row['file_col']
                things[(row['extent_start'],row['extent_end'])] = (kind,id,line,col,' ')
        for k,v in things.iteritems():
            allthings[k] = self.identify(v)
        things = {}
        for row in self.cursor.execute('SELECT decl_file_id,decl_file_line, decl_file_col, ' \
                                       'extent_start, extent_end'+getname+ \
                                       ' FROM %s_refs WHERE extent_start NOT NULL AND decl_file_id NOT NULL AND file_id=?'%kind, (id,)):
            fid, line, col = row['decl_file_id'], row['decl_file_line'],row['decl_file_col']
            if kind == 'macro':
                name = ''
            else:
                name = row[defn_name(kind)]
            things[(row['extent_start'],row['extent_end'])] = (kind,fid,line,col,name)
        for k,v in things.iteritems():
            allthings[k] = self.identify(v)
        things = {}
        for row in self.cursor.execute('SELECT decl_file_id,decl_file_line,decl_file_col, ' \
                                       'extent_start,extent_end,'+defn_name(kind)+ \
                                       ' FROM '+kind+'s WHERE '+defn_id(kind)+'=? AND extent_start NOT NULL ', (id,)):
            fid, line, col = row['decl_file_id'],row['decl_file_line'],row['decl_file_col']
            name = row[defn_name(kind)]
            things[(row['extent_start'],row['extent_end'])] = (kind,fid,line,col,name)
        for k,v in things.iteritems():
            allthings[k] = self.identify(v)

        objs = set()
        for k,v in allthings.iteritems():
            if v:
                start,end = k
                kind,fid,line,col,name,type = v
                sys.stdout.write('(r %s %d %d %d %d %d)\n'%(kind,fid,line,col,start,end))
                objs.add((kind,fid,line,col,name,type))

        for k in objs:
            kind,fid,line,col,name,type = k
            sys.stdout.write('(decl %s %d %d %d "%s"'%(kind,fid,line,col,name))
            if type:
                sys.stdout.write(' "%s"'%type)
            sys.stdout.write(')\n')

    def read_files(self):
        self.file = {}
        for row in self.cursor.execute('SELECT id,path FROM files'):
            self.file[int(row[0])] = row[1]

    def show_info(self,kind,id,line,col):
        if kind=='function':
            sys.stdout.write('Declaraton:\n')
            for row in self.cursor.execute('SELECT path FROM files WHERE id=?',(id,)):
                sys.stdout.write('%s:%s:%s\n'%(row['path'],line,col))
            sys.stdout.write('\nDefinition:\n')
            override_id = None
            for row in self.cursor.execute('SELECT path,file_line,file_col,override_file_id,override_file_line,override_file_col FROM ' \
                                           'functions,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=?',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))
                override_id,override_line,override_col = row['override_file_id'],row['override_file_line'],row['override_file_col']
            if override_id:
                sys.stdout.write('\nOverrides:\n')
                for row in self.cursor.execute('SELECT path,qualname FROM functions,files WHERE decl_file_id=id AND ' \
                                               'decl_file_id=? AND decl_file_line=? AND decl_file_col=?',(override_id,override_line,override_col)):
                    sys.stdout.write('%s:%d:%d  %s\n'%(row[0],override_line,override_col,row[1]))
            overrides = []
            for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,qualname FROM functions,files WHERE ' \
                                           'decl_file_id = id AND ' \
                                           'override_file_id = ? AND ' \
                                           'override_file_line = ? AND ' \
                                           'override_file_col = ?', (id,line,col)):
                overrides.append((row[0],row[1],row[2],row[3]))
            if len(overrides) > 0:
                sys.stdout.write('\nIs overridden by:\n')
                for val in overrides:
                    o_path,o_line,o_col,o_qualname = val
                    sys.stdout.write('%s:%d:%d  %s\n'%(o_path,o_line,o_col,o_qualname))
            sys.stdout.write('\nReferences:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col FROM ' \
                                           'function_refs,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=? ORDER BY path,file_line',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))

        if kind=='variable':
            sys.stdout.write('Declaraton:\n')
            for row in self.cursor.execute('SELECT path FROM files WHERE id=?',(id,)):
                sys.stdout.write('%s:%s:%s\n'%(row['path'],line,col))
            sys.stdout.write('\nDefinition:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col FROM ' \
                                           'variables,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=?',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))
            sys.stdout.write('\nReferences:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col FROM ' \
                                           'variable_refs,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=? ORDER BY path,file_line',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))

        if kind=='type':
            sys.stdout.write('Declaraton:\n')
            for row in self.cursor.execute('SELECT path FROM files WHERE id=?',(id,)):
                sys.stdout.write('%s:%s:%s\n'%(row['path'],line,col))
            sys.stdout.write('\nDefinition:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col,kind FROM '+ \
                                           'types,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=?',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))
                k = row[3]
            if k=='enum':
                variables = []
                for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,name ' \
                                               'FROM variables,files WHERE decl_file_id=id AND ' \
                                               'scope_file_id=? AND scope_file_line=? AND scope_file_col=? ' \
                                               'ORDER BY decl_file_line',
                                               (id,line,col)):
                    variables.append('%s:%d:%d  %s'%(row[0],row[1],row[2],row[3]))
                if len(variables)>0:
                    sys.stdout.write('\nEnums:\n')
                    sys.stdout.write('\n'.join(variables)+'\n')

            if k=='struct' or k=='class':
                superclasses = []
                for row in self.cursor.execute('SELECT path,base_file_line,base_file_col,qualname ' \
                                               'FROM impl,files,types WHERE base_file_id=id AND ' \
                                               'base_file_id = decl_file_id AND ' \
                                               'base_file_line = decl_file_line AND ' \
                                               'base_file_col = decl_file_col AND ' \
                                               'impl.file_id=? AND impl.file_line=? AND impl.file_col=?',
                                               (id,line,col)):
                    superclasses.append('%s:%d:%d  %s'%(row['path'],row['base_file_line'],
                                                        row['base_file_col'],row['qualname']))
                if len(superclasses) > 0:
                    sys.stdout.write('\nSuperclasses:\n')
                    sys.stdout.write('\n'.join(superclasses)+'\n')

                typedefs = []
                for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,qualname,modifiers ' \
                                               'FROM typedefs,files WHERE decl_file_id=id AND ' \
                                               'scope_file_id=? AND scope_file_line=? AND scope_file_col=? ' \
                                               'ORDER BY modifiers,decl_file_line',
                                               (id,line,col)):
                    if row[4]:
                        access = row[4]
                    else:
                        access = 'public'
                    typedefs.append('%s:%d:%d  %s: %s'%(row[0],row[1],row[2],access,row[3]))
                if len(typedefs)>0:
                    sys.stdout.write('\nTypedef members:\n')
                    sys.stdout.write('\n'.join(typedefs)+'\n')

                types = []
                for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,qualname,modifiers ' \
                                               'FROM types,files WHERE decl_file_id=id AND ' \
                                               'scope_file_id=? AND scope_file_line=? AND scope_file_col=? ' \
                                               'ORDER BY modifiers,decl_file_line',
                                               (id,line,col)):
                    if row[4]:
                        access = row[4]
                    else:
                        access = 'public'
                    types.append('%s:%d:%d  %s: %s'%(row[0],row[1],row[2],access,row[3]))
                if len(types)>0:
                    sys.stdout.write('\nType members:\n')
                    sys.stdout.write('\n'.join(types)+'\n')

                variables = []
                for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,qualname,type,modifiers ' \
                                               'FROM variables,files WHERE decl_file_id=id AND ' \
                                               'scope_file_id=? AND scope_file_line=? AND scope_file_col=? ' \
                                               'ORDER BY modifiers,decl_file_line',
                                               (id,line,col)):
                    if row[5]:
                        access = row[5]
                    else:
                        access = 'public'
                    variables.append('%s:%d:%d  %s: %s %s'%(row[0],row[1],row[2],access,row[4],row[3]))
                if len(variables)>0:
                    sys.stdout.write('\nData members:\n')
                    sys.stdout.write('\n'.join(variables)+'\n')

                members = []
                for row in self.cursor.execute('SELECT path,decl_file_line,decl_file_col,qualname,type,modifiers ' \
                                               'FROM functions,files WHERE decl_file_id=id AND ' \
                                               'scope_file_id=? AND scope_file_line=? AND scope_file_col=? ' \
                                               'ORDER BY modifiers,decl_file_line',
                                               (id,line,col)):
                    if row[5]:
                        access = row[5]
                    else:
                        access = 'public'
                    members.append('%s:%d:%d  %s: %s %s'%(row[0],row[1],row[2],access,row[4],row[3]))
                if len(members)>0:
                    sys.stdout.write('\nMember functions:\n')
                    sys.stdout.write('\n'.join(members)+'\n')

                subclasses = []
                for row in self.cursor.execute('SELECT path,impl.file_line,impl.file_col,qualname ' \
                                               'FROM impl,files,types where impl.file_id=id AND ' \
                                               'impl.file_id = decl_file_id AND ' \
                                               'impl.file_line = decl_file_line AND ' \
                                               'impl.file_col = decl_file_col AND ' \
                                               'base_file_id=? AND base_file_line=? AND base_file_col=?',
                                               (id,line,col)):
                    subclasses.append('%s:%d:%d  %s'%(row['path'],row['file_line'],
                                                      row['file_col'],row['qualname']))
                if len(subclasses) > 0:
                    sys.stdout.write('\nSubclasses:\n')
                    sys.stdout.write('\n'.join(subclasses)+'\n')
            sys.stdout.write('\nReferences:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col FROM '+ \
                                           kind+'_refs,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=? ORDER BY path,file_line',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))

        if kind=='macro' or kind=='typedef':
            sys.stdout.write('Definition:\n')
            for row in self.cursor.execute('SELECT path FROM files WHERE id=?',(id,)):
                sys.stdout.write('%s:%s:%s\n'%(row['path'],line,col))
            sys.stdout.write('\nReferences:\n')
            for row in self.cursor.execute('SELECT path,file_line,file_col FROM '+ \
                                           kind+'_refs,files WHERE ' \
                                           'file_id = id AND ' \
                                           'decl_file_id=? AND ' \
                                           'decl_file_line=? AND ' \
                                           'decl_file_col=? ORDER BY path,file_line',(id,line,col)):
                sys.stdout.write('%s:%d:%d\n'%(row[0],row[1],row[2]))

    def show_search(self, type, string):
        if type=='exact':
            search = '== ?'
        elif type=='prefix':
            search = 'GLOB ?'
            string += '*'
        elif type=='glob':
            search = 'GLOB ?'
        elif type=='substring':
            search = 'GLOB ?'
            string = '*'+string+'*'
        for kind in ['function','variable','type','typedef','macro']:
            if kind=='macro':
                name='name'
            else:
                name='qualname'
            results = []
            for row in self.cursor.execute('SELECT %s,path,decl_file_line,decl_file_col ' \
                                           'FROM %ss,files WHERE decl_file_id=id AND %s %s ' \
                                           'ORDER BY path,decl_file_line'%(name,kind,name,search),
                                           (string,)):
                results.append((row[0],row[1],row[2],row[3]))
            if len(results)>0:
                sys.stdout.write('\n%ss:\n'%kind)
                for v in results:
                    name,path,line,col = v
                    sys.stdout.write('%s:%d:%d  %s\n'%(path,line,col,name))

def defn_id(kind):
    if kind == 'function' or kind == 'variable' or kind == 'type':
        return 'file_id'
    else:
        return 'decl_file_id'

def defn_line(kind):
    if kind == 'function' or kind == 'variable' or kind == 'type':
        return 'file_line'
    else:
        return 'decl_file_line'

def defn_col(kind):
    if kind == 'function' or kind == 'variable' or kind == 'type':
        return 'file_col'
    else:
        return 'decl_file_col'

def defn_name(kind):
    if kind == 'macro':
        return 'name'
    else:
        return 'qualname'

def posn(p):
    if p==None or p=='':
        return 0
    else:
        return p+1

def relpath(path, root):
    return os.path.relpath(os.path.join(root, path), os.path.abspath(os.path.curdir))

def decorate(args):
    name=os.path.relpath(os.path.realpath(os.path.abspath(args.name)),args.database)
    file_id = args.idx.find_file_id(name)
    if file_id:
        sys.stdout.write('(root "%s")\n'%args.database)
        sys.stdout.write('(self "%s")\n'%name)
        args.idx.show_includes(file_id)
        args.idx.decoration(file_id)

def info(args):
    id, line, col = args.id, args.line, args.col
    args.idx.show_info(args.kind, id, line, col)

def search(args):
    args.idx.show_search(args.type, args.string)

def main():
    import argparse
    import os
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    parser_decorate = subparsers.add_parser('decorate')
    parser_decorate.add_argument('name')
    parser_decorate.set_defaults(func=decorate)

    parser_menu = subparsers.add_parser('info')
    parser_menu.add_argument('kind')
    parser_menu.add_argument('id')
    parser_menu.add_argument('line')
    parser_menu.add_argument('col')
    parser_menu.set_defaults(func=info)

    parser_search = subparsers.add_parser('search')
    parser_search.add_argument('-t','--type', choices=['exact','prefix','glob','substring'], default='substring')
    parser_search.add_argument('string')
    parser_search.set_defaults(func=search)

    args = parser.parse_args()
    args.database = os.path.realpath(os.path.abspath(os.curdir))
    while args.database != '/' and not os.path.exists(os.path.join(args.database,'dxr-xref.sqlite')):
        args.database = os.path.dirname(args.database)
    args.idx = index(os.path.join(args.database,'dxr-xref.sqlite'))

    args.idx.database = args.database

    args.func(args)

if __name__ == '__main__':
    main()
