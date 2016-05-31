# (C) William W. Cohen and Carnegie Mellon University, 2016

import re
import os.path
import collections
import scipy.sparse as SS
import scipy.io as SIO

import mutil
import matrixdb
import declare

#
# dealing with labeled training data
#

class Dataset(object):
    
    def __init__(self,xDict,yDict):
        # dict which maps mode declaration to X matrices for training
        self.xDict = xDict
        # likewise for Y matrices
        self.yDict = yDict

    def modesToLearn(self):
        """Return list of modes associated with the data."""
        return self.xDict.keys()

    def getX(self,mode):
        return self.xDict[mode]

    def getY(self,mode):
        return self.yDict[mode]

    def pprint(self):
        return ['%s: X %s Y %s' % (str(mode),mutil.summary(self.xDict[mode]),mutil.summary(self.yDict[mode])) for mode in self.xDict]

    #
    # i/o and conversions
    # 

    def serialize(self,dir):
        if not os.path.exists(dir):
            os.mkdir(dir)
        #print 'serialized keys',self.xDict.keys(),self.yDict.keys()
        dx = dict(map(lambda (k,v):(str(k),v), self.xDict.items()))
        dy = dict(map(lambda (k,v):(str(k),v), self.yDict.items()))
        SIO.savemat(os.path.join(dir,"xDict"),dx,do_compression=True)
        SIO.savemat(os.path.join(dir,"yDict"),dy,do_compression=True)
        
    @staticmethod
    def deserialize(dir):
        xDict = {}
        yDict = {}
        SIO.loadmat(os.path.join(dir,"xDict"),xDict)
        SIO.loadmat(os.path.join(dir,"yDict"),yDict)
        #serialization converts nodes to strings so convert them back....
        for d in (xDict,yDict):
            for stringKey,mat in d.items():
                del d[stringKey]
                if not stringKey.startswith('__'):
                    d[declare.asMode(stringKey)] = mat
        #print 'deserialized keys',xDict.keys(),yDict.keys()
        return Dataset(xDict,yDict)

    @staticmethod
    def uncacheExamples(dsetFile,db,exampleFile):
        """Build a dataset file from an examples file, serialize it, and
        return the de-serialized dataset.  Or if that's not necessary,
        just deserialize it.
        """
        if not os.path.exists(dsetFile) or os.path.getmtime(exampleFile)>os.path.getmtime(dsetFile):
            print 'loading exampleFile',exampleFile,'...'
            dset = Dataset.loadProPPRExamples(db,exampleFile)
            print 'serializing dsetFile',dsetFile,'...'
            dset.serialize(dsetFile)
            return dset
        else:
            print 'de-serializing dsetFile',dsetFile,'...'
            return Dataset.deserialize(dsetFile)

    @staticmethod
    def uncacheMatrix(dsetFile,db,functorToLearn,functorInDB):
        """Build a dataset file from a DB matrix as specified with loadMatrix
        and serialize it.  Or if that's not necessary, just
        deserialize it.
        """
        if not os.path.exists(dsetFile):
            print 'preparing examples from',functorToLearn,'...'
            dset = Dataset.loadMatrix(db,functorToLearn,functorInDB)
            print 'serializing dsetFile',dsetFile,'...'
            dset.serialize(dsetFile)
            return dset
        else:
            print 'de-serializing dsetFile',dsetFile,'...'
            return Dataset.deserialize(dsetFile)

    @staticmethod
    def loadMatrix(db,functorToLearn,functorInDB):
        """Convert a DB matrix containing pairs x,f(x) to training data for a
        learner.  For each row x with non-zero entries, copy that row
        to Y, and and also append a one-hot representation of x to the
        corresponding row of X.
        """
        functorToLearn = declare.asMode(functorToLearn)
        xrows = []
        yrows = []
        m = db.matEncoding[(functorInDB,2)].tocoo()
        n = db.dim()
        for i in range(len(m.data)):
            x = m.row[i]            
            xrows.append(SS.csr_matrix( ([1.0],([0],[x])), shape=(1,n) ))
            rx = m.getrow(x)
            yrows.append(rx.multiply(1.0/rx.sum()))
        return Dataset({functorToLearn:mutil.stack(xrows)},{functorToLearn:mutil.stack(yrows)})

    @staticmethod
    #TODO refactor to also load examples in form: 'functor X Y1
    #... Yk'

    def loadProPPRExamples(db,fileName):
        """Convert a foo.examples file to a two dictionaries of
        modename->matrix pairs, one for the Xs, one for the Ys"""
        xsTmp = collections.defaultdict(list)
        ysTmp = collections.defaultdict(list)
        regex = re.compile('(\w+)\((\w+),(\w+)\)')
        fp = open(fileName)
        for line in fp:
            parts = line.strip().split("\t")
            mx = regex.search(parts[0])
            if mx:
                pred = declare.asMode(mx.group(1)+"/io")
                x = mx.group(2)
                pos = []
                for ans in parts[1:]:
                    label = ans[0]
                    my = regex.search(ans[1:])
                    assert my,'problem at line '+line
                    assert my.group(1)==pred.functor,'mismatched preds %s %s at line %s' % (my.group(1),pred,line)
                    assert my.group(2)==x,'mismatched x\'s at line '+line
                    if label=='+':
                        pos.append(my.group(3))
                xsTmp[pred].append(x)
                ysTmp[pred].append(pos)
        xsResult = {}
        for pred in xsTmp.keys():
            xRows = map(lambda x:db.onehot(x), xsTmp[pred])
            xsResult[pred] = mutil.stack(xRows)
        ysResult = {}
        for pred in ysTmp.keys():
            def yRow(ys):
                accum = db.onehot(ys[0])
                for y in ys[1:]:
                    accum = accum + db.onehot(y)
                accum = accum * 1.0/len(ys)
                return accum
            yRows = map(yRow, ysTmp[pred])
            ysResult[pred] = mutil.stack(yRows)
        return Dataset(xsResult,ysResult)

    #TODO refactor to also save examples in form: 'functor X Y1
    #... Yk'
    def saveProPPRExamples(self,fileName,db,append=False):
        """Convert X and Y to ProPPR examples and store in a file."""
        fp = open(fileName,'a' if append else 'w')
        for mode in self.xDict:
            assert mode in self.yDict
            dx = db.matrixAsSymbolDict(self.xDict[mode])
            dy = db.matrixAsSymbolDict(self.yDict[mode])
            theoryPred = mode.functor
            for i in range(max(dx.keys())):
                dix = dx[i]
                diy = dy[i]
                assert len(dix.keys())==1,'X row %d is not onehot: %r' % (i,dix)
                x = dix.keys()[0]
                fp.write('%s(%s,Y)' % (theoryPred,x))
                for y in diy.keys():
                    fp.write('\t+%s(%s,%s)' % (theoryPred,x,y))
                fp.write('\n')

if __name__=="__main__":
    db = matrixdb.MatrixDB.uncache('tmp-toy.db','test/textcattoy.cfacts')
    trainData = Dataset.loadMatrix(db,'predict/io','train')
    trainData.serialize("foo.dset")
    newTrainData = Dataset.deserialize("foo.dset")

    
