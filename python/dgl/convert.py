"""Module for converting graph from/to other object."""
from collections import defaultdict
import numpy as np
import scipy as sp
import networkx as nx

from . import backend as F
from . import heterograph_index
from .heterograph import DGLHeteroGraph, combine_frames
from . import graph_index
from . import utils
from .base import NTYPE, ETYPE, NID, EID

__all__ = [
    'graph',
    'bipartite',
    'hetero_from_relations',
    'to_hetero',
    'to_homo',
    'to_networkx',
]

def graph(data, ntype='_N', etype='_E', card=None, **kwargs):
    """Create a graph.

    The graph has only one type of nodes and edges.

    In the sparse matrix perspective, :func:`dgl.graph` creates a graph
    whose adjacency matrix must be square while :func:`dgl.bipartite`
    creates a graph that does not necessarily have square adjacency matrix.

    Examples
    --------
    Create from edges pairs:

    >>> g = dgl.graph([(0, 2), (0, 3), (1, 2)])

    Creat from pair of vertex IDs lists

    >>> u = [0, 0, 1]
    >>> v = [2, 3, 2]
    >>> g = dgl.graph((u, v))

    The IDs can also be stored in framework-specific tensors

    >>> import torch
    >>> u = torch.tensor([0, 0, 1])
    >>> v = torch.tensor([2, 3, 2])
    >>> g = dgl.graph((u, v))

    Create from scipy sparse matrix

    >>> from scipy.sparse import coo_matrix
    >>> spmat = coo_matrix(([1,1,1], ([0, 0, 1], [2, 3, 2])), shape=(4, 4))
    >>> g = dgl.graph(spmat)

    Create from networkx graph

    >>> import networkx as nx
    >>> nxg = nx.path_graph(3)
    >>> g = dgl.graph(nxg)

    Specify node and edge type names

    >>> g = dgl.graph(..., 'user', 'follows')
    >>> g.ntypes
    ['user']
    >>> g.etypes
    ['follows']
    >>> g.canonical_etypes
    [('user', 'follows', 'user')]

    Parameters
    ----------
    data : graph data
        Data to initialize graph structure. Supported data formats are
        (1) list of edge pairs (e.g. [(0, 2), (3, 1), ...])
        (2) pair of vertex IDs representing end nodes (e.g. ([0, 3, ...],  [2, 1, ...]))
        (3) scipy sparse matrix
        (4) networkx graph
    ntype : str, optional
        Node type name. (Default: _N)
    etype : str, optional
        Edge type name. (Default: _E)
    card : int, optional
        Cardinality (number of nodes in the graph). If None, infer from input data.
        (Default: None)
    kwargs : key-word arguments, optional
        Other key word arguments.

    Returns
    -------
    DGLHeteroGraph
    """
    if card is not None:
        urange, vrange = card, card
    else:
        urange, vrange = None, None
    if isinstance(data, tuple):
        u, v = data
        return create_from_edges(u, v, ntype, etype, ntype, urange, vrange)
    elif isinstance(data, list):
        return create_from_edge_list(data, ntype, etype, ntype, urange, vrange)
    elif isinstance(data, sp.sparse.spmatrix):
        return create_from_scipy(data, ntype, etype, ntype)
    elif isinstance(data, nx.Graph):
        return create_from_networkx(data, ntype, etype, **kwargs)
    else:
        raise DGLError('Unsupported graph data type:', type(data))

def bipartite(data, utype='_U', etype='_E', vtype='_V', card=None, **kwargs):
    """Create a bipartite graph.

    The result graph is directed and edges must be from ``utype`` nodes
    to ``vtype`` nodes. Nodes of each type have their own ID counts.

    In the sparse matrix perspective, :func:`dgl.graph` creates a graph
    whose adjacency matrix must be square while :func:`dgl.bipartite`
    creates a graph that does not necessarily have square adjacency matrix.

    Examples
    --------
    Create from edges pairs:

    >>> g = dgl.bipartite([(0, 2), (0, 3), (1, 2)], 'user', 'plays', 'game')
    >>> g.ntypes
    ['user', 'game']
    >>> g.etypes
    ['plays']
    >>> g.canonical_etypes
    [('user', 'plays', 'game')]
    >>> g.number_of_nodes('user')
    2
    >>> g.number_of_nodes('game')
    4
    >>> g.number_of_edges('plays')  # 'plays' could be omitted here
    3

    Creat from pair of vertex IDs lists

    >>> u = [0, 0, 1]
    >>> v = [2, 3, 2]
    >>> g = dgl.bipartite((u, v))

    The IDs can also be stored in framework-specific tensors

    >>> import torch
    >>> u = torch.tensor([0, 0, 1])
    >>> v = torch.tensor([2, 3, 2])
    >>> g = dgl.bipartite((u, v))

    Create from scipy sparse matrix. Since scipy sparse matrix has explicit
    shape, the cardinality of the result graph is derived from that.

    >>> from scipy.sparse import coo_matrix
    >>> spmat = coo_matrix(([1,1,1], ([0, 0, 1], [2, 3, 2])), shape=(4, 4))
    >>> g = dgl.bipartite(spmat, 'user', 'plays', 'game')
    >>> g.number_of_nodes('user')
    4
    >>> g.number_of_nodes('game')
    4

    Create from networkx graph. The given graph must follow the bipartite
    graph convention in networkx. Each node has a ``bipartite`` attribute
    with values 0 or 1. The result graph has two types of nodes and only
    edges from ``bipartite=0`` to ``bipartite=1`` will be included.

    >>> import networkx as nx
    >>> nxg = nx.complete_bipartite_graph(3, 4)
    >>> g = dgl.graph(nxg, 'user', 'plays', 'game')
    >>> g.number_of_nodes('user')
    3
    >>> g.number_of_nodes('game')
    4
    >>> g.edges()
    (tensor([0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]), tensor([0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]))

    Parameters
    ----------
    data : graph data
        Data to initialize graph structure. Supported data formats are
        (1) list of edge pairs (e.g. [(0, 2), (3, 1), ...])
        (2) pair of vertex IDs representing end nodes (e.g. ([0, 3, ...],  [2, 1, ...]))
        (3) scipy sparse matrix
        (4) networkx graph
    utype : str, optional
        Source node type name. (Default: _U)
    etype : str, optional
        Edge type name. (Default: _E)
    vtype : str, optional
        Destination node type name. (Default: _V)
    card : pair of int, optional
        Cardinality (number of nodes in the source and destination group). If None,
        infer from input data.  (Default: None)
    kwargs : key-word arguments, optional
        Other key word arguments.

    Returns
    -------
    DGLHeteroGraph
    """
    if utype == vtype:
        raise DGLError('utype should not be equal to vtype. Use ``dgl.graph`` instead.')
    if card is not None:
        urange, vrange = card
    else:
        urange, vrange = None, None
    if isinstance(data, tuple):
        u, v = data
        return create_from_edges(u, v, utype, etype, vtype, urange, vrange)
    elif isinstance(data, list):
        return create_from_edge_list(data, utype, etype, vtype, urange, vrange)
    elif isinstance(data, sp.sparse.spmatrix):
        return create_from_scipy(data, utype, etype, vtype)
    elif isinstance(data, nx.Graph):
        return create_from_networkx_bipartite(data, utype, etype, vtype, **kwargs)
    else:
        raise DGLError('Unsupported graph data type:', type(data))

def hetero_from_relations(rel_graphs):
    """Create a heterograph from per-relation graphs.

    TODO(minjie): this API can be generalized as a union operation of
    the input graphs

    TODO(minjie): handle node/edge data

    Parameters
    ----------
    rel_graphs : list of DGLHeteroGraph
        Graph for each relation.

    Returns
    -------
    DGLHeteroGraph
        A heterograph.
    """
    # infer meta graph
    ntype_dict = {}  # ntype -> ntid
    meta_edges = []
    ntypes = []
    etypes = []
    for rgrh in rel_graphs:
        assert len(rgrh.etypes) == 1
        stype, etype, dtype = rgrh.canonical_etypes[0]
        if not stype in ntype_dict:
            ntype_dict[stype] = len(ntypes)
            ntypes.append(stype)
        stid = ntype_dict[stype]
        if not dtype in ntype_dict:
            ntype_dict[dtype] = len(ntypes)
            ntypes.append(dtype)
        dtid = ntype_dict[dtype]
        meta_edges.append((stid, dtid))
        etypes.append(etype)
    metagraph = graph_index.from_edge_list(meta_edges, True, True)
    # create graph index
    hgidx = heterograph_index.create_heterograph_from_relations(
        metagraph, [rgrh._graph for rgrh in rel_graphs])
    retg = DGLHeteroGraph(hgidx, ntypes, etypes)
    for i, rgrh in enumerate(rel_graphs):
        for ntype in rgrh.ntypes:
            retg.nodes[ntype].data.update(rgrh.nodes[ntype].data)
        retg._edge_frames[i].update(rgrh._edge_frames[0])
    return retg

def to_hetero(G, ntypes, etypes, ntype_field=NTYPE, etype_field=ETYPE, metagraph=None):
    """Convert the given graph to a heterogeneous graph.

    The input graph should have only one type of nodes and edges. Each node and edge
    stores an integer feature (under ``ntype_field`` and ``etype_field``), representing
    the type id, which which can be used to retrieve the type names stored
    in the given ``ntypes`` and ``etypes`` arguments.

    Examples
    --------
    TBD

    Parameters
    ----------
    G : DGLHeteroGraph
        Input homogenous graph.
    ntypes : list of str
        The node type names.
    etypes : list of str
        The edge type names.
    ntype_field : str, optional
        The feature field used to store node type. (Default: dgl.NTYPE)
    etype_field : str, optional
        The feature field used to store edge type. (Default: dgl.ETYPE)
    metagraph : networkx MultiDiGraph, optional
        Metagraph of the returned heterograph.
        If provided, DGL assumes that G can indeed be described with the given metagraph.
        If None, DGL will infer the metagraph from the given inputs, which would be
        potentially slower for large graphs.

    Returns
    -------
    DGLHeteroGraph
        A heterograph.
        The parent node and edge ID are stored in the column dgl.NID and dgl.EID
        respectively for all node/edge types.

    Notes
    -----
    The returned node and edge types may not necessarily be in the same order as
    ``ntypes`` and ``etypes``.  And edge types may be duplicated if the source
    and destination types differ.

    The node IDs of a single type in the returned heterogeneous graph is ordered
    the same as the nodes with the same ``ntype_field`` feature.  Edge IDs of
    a single type is similar.
    """
    # TODO(minjie): use hasattr to support DGLGraph input; should be fixed once
    #  DGLGraph is merged with DGLHeteroGraph
    if (hasattr(G, 'ntypes') and len(G.ntypes) > 1
            or hasattr(G, 'etypes') and len(G.etypes) > 1):
        raise DGLError('The input graph should be homogenous and have only one '
                       ' type of nodes and edges.')

    num_ntypes = len(ntypes)

    ntype_ids = F.asnumpy(G.ndata[ntype_field])
    etype_ids = F.asnumpy(G.edata[etype_field])

    # relabel nodes to per-type local IDs
    ntype_count = np.bincount(ntype_ids, minlength=num_ntypes)
    ntype_offset = np.insert(np.cumsum(ntype_count), 0, 0)
    ntype_ids_sortidx = np.argsort(ntype_ids)
    ntype_local_ids = np.zeros_like(ntype_ids)
    node_groups = []
    for i in range(num_ntypes):
        node_group = ntype_ids_sortidx[ntype_offset[i]:ntype_offset[i+1]]
        node_groups.append(node_group)
        ntype_local_ids[node_group] = np.arange(ntype_count[i])

    src, dst = G.all_edges(order='eid')
    src = F.asnumpy(src)
    dst = F.asnumpy(dst)
    src_local = ntype_local_ids[src]
    dst_local = ntype_local_ids[dst]
    srctype_ids = ntype_ids[src]
    dsttype_ids = ntype_ids[dst]
    canon_etype_ids = np.stack([srctype_ids, etype_ids, dsttype_ids], 1)

    # infer metagraph
    if metagraph is None:
        canonical_etids, _, etype_remapped = \
                utils.make_invmap(list(tuple(_) for _ in canon_etype_ids), False)
        etype_mask = (etype_remapped[None, :] == np.arange(len(canonical_etids))[:, None])
    else:
        ntypes_invmap = {nt: i for i, nt in enumerate(ntypes)}
        etypes_invmap = {et: i for i, et in enumerate(etypes)}
        canonical_etids = []
        etype_remapped = np.zeros(etype_ids)
        for i, (srctype, dsttype, etype) in enumerate(metagraph.edges(keys=True)):
            srctype_id = ntypes_invmap[srctype]
            etype_id = etypes_invmap[etype]
            dsttype_id = ntypes_invmap[dsttype]
            canonical_etids.append((srctype_id, etype_id, dsttype_id))
        canonical_etids = np.array(canonical_etids)
        etype_mask = (canon_etype_ids[None, :] == canonical_etids[:, None]).all(2)
    edge_groups = [etype_mask[i].nonzero()[0] for i in range(len(canonical_etids))]

    rel_graphs = []
    for i, (stid, etid, dtid) in enumerate(canonical_etids):
        src_of_etype = src_local[edge_groups[i]]
        dst_of_etype = dst_local[edge_groups[i]]
        if stid == dtid:
            rel_graph = graph(
                (src_of_etype, dst_of_etype), ntypes[stid], etypes[etid],
                card=ntype_count[stid])
        else:
            rel_graph = bipartite(
                (src_of_etype, dst_of_etype), ntypes[stid], etypes[etid], ntypes[dtid],
                card=(ntype_count[stid], ntype_count[dtid]))
        rel_graphs.append(rel_graph)

    hg = hetero_from_relations(rel_graphs)

    ntype2ngrp = {ntype : node_groups[ntid] for ntid, ntype in enumerate(ntypes)}
    for ntid, ntype in enumerate(hg.ntypes):
        hg._node_frames[ntid][NID] = F.tensor(ntype2ngrp[ntype])

    for etid in range(len(hg.canonical_etypes)):
        hg._edge_frames[etid][EID] = F.tensor(edge_groups[etid])

    # features
    for key, data in G.ndata.items():
        for ntid, ntype in enumerate(hg.ntypes):
            rows = F.copy_to(F.tensor(ntype2ngrp[ntype]), F.context(data))
            hg._node_frames[ntid][key] = F.gather_row(data, rows)
    for key, data in G.edata.items():
        for etid in range(len(hg.canonical_etypes)):
            rows = F.copy_to(F.tensor(edge_groups[etid]), F.context(data))
            hg._edge_frames[etid][key] = F.gather_row(data, rows)

    return hg

def to_homo(G):
    """Convert the given graph to a homogeneous graph.

    The returned graph has only one type of nodes and etypes.

    Node and edge types are stored as features in the returned graph. Each feature
    is an integer representing the type id, which can be used to retrieve the type
    names stored in ``G.ntypes`` and ``G.etypes`` arguments.

    Examples
    --------
    TBD

    Parameters
    ----------
    G : DGLHeteroGraph
        Input heterogenous graph.

    Returns
    -------
    DGLHeteroGraph
        A homogenous graph.
        The parent node and edge type/ID are stored in columns dgl.NTYPE/dgl.NID and
        dgl.ETYPE/dgl.EID respectively.
    """
    num_nodes_per_ntype = [G.number_of_nodes(ntype) for ntype in G.ntypes]
    offset_per_ntype = np.insert(np.cumsum(num_nodes_per_ntype), 0, 0)
    srcs = []
    dsts = []
    etype_ids = []
    eids = []
    ntype_ids = []
    nids = []

    for ntype_id, ntype in enumerate(G.ntypes):
        num_nodes = G.number_of_nodes(ntype)
        ntype_ids.append(F.full_1d(num_nodes, ntype_id, F.int64, F.cpu()))
        nids.append(F.arange(0, num_nodes))

    for etype_id, etype in enumerate(G.canonical_etypes):
        srctype, _, dsttype = etype
        src, dst = G.all_edges(etype=etype, order='eid')
        num_edges = len(src)
        srcs.append(src + offset_per_ntype[G.get_ntype_id(srctype)])
        dsts.append(dst + offset_per_ntype[G.get_ntype_id(dsttype)])
        etype_ids.append(F.full_1d(num_edges, etype_id, F.int64, F.cpu()))
        eids.append(F.arange(0, num_edges))

    retg = graph((F.cat(srcs, 0), F.cat(dsts, 0)))
    retg.ndata[NTYPE] = F.cat(ntype_ids, 0)
    retg.ndata[NID] = F.cat(nids, 0)
    retg.edata[ETYPE] = F.cat(etype_ids, 0)
    retg.edata[EID] = F.cat(eids, 0)

    # features
    comb_nf = combine_frames(G._node_frames, range(len(G.ntypes)))
    comb_ef = combine_frames(G._edge_frames, range(len(G.etypes)))
    if comb_nf is not None:
        retg.ndata.update(comb_nf)
    if comb_ef is not None:
        retg.edata.update(comb_ef)

    return retg

############################################################
# Internal APIs
############################################################

def create_from_edges(u, v, utype, etype, vtype, urange=None, vrange=None):
    """Internal function to create a graph from incident nodes with types.

    utype could be equal to vtype

    Parameters
    ----------
    u : iterable of int
        List of source node IDs.
    v : iterable of int
        List of destination node IDs.
    utype : str
        Source node type name.
    etype : str
        Edge type name.
    vtype : str
        Destination node type name.
    urange : int, optional
        The source node ID range. If None, the value is the maximum
        of the source node IDs in the edge list plus 1. (Default: None)
    vrange : int, optional
        The destination node ID range. If None, the value is the
        maximum of the destination node IDs in the edge list plus 1. (Default: None)

    Returns
    ------
    DGLHeteroGraph
    """
    u = utils.toindex(u)
    v = utils.toindex(v)
    urange = urange or (int(F.asnumpy(F.max(u.tousertensor(), dim=0))) + 1)
    vrange = vrange or (int(F.asnumpy(F.max(v.tousertensor(), dim=0))) + 1)
    if utype == vtype:
        urange = vrange = max(urange, vrange)
        num_ntypes = 1
    else:
        num_ntypes = 2
    hgidx = heterograph_index.create_unitgraph_from_coo(num_ntypes, urange, vrange, u, v)
    if utype == vtype:
        return DGLHeteroGraph(hgidx, [utype], [etype])
    else:
        return DGLHeteroGraph(hgidx, [utype, vtype], [etype])

def create_from_edge_list(elist, utype, etype, vtype, urange=None, vrange=None):
    """Internal function to create a graph from a list of edge tuples with types.

    utype could be equal to vtype

    Examples
    --------
    TBD

    Parameters
    ----------
    elist : iterable of int pairs
        List of (src, dst) node ID pairs.
    utype : str
        Source node type name.
    etype : str
        Edge type name.
    vtype : str
        Destination node type name.
    urange : int, optional
        The source node ID range. If None, the value is the maximum
        of the source node IDs in the edge list plus 1. (Default: None)
    vrange : int, optional
        The destination node ID range. If None, the value is the
        maximum of the destination node IDs in the edge list plus 1. (Default: None)

    Returns
    -------
    DGLHeteroGraph
    """
    if len(elist) == 0:
        u, v = [], []
    else:
        u, v = zip(*elist)
        u = list(u)
        v = list(v)
    return create_from_edges(u, v, utype, etype, vtype, urange, vrange)

def create_from_scipy(spmat, utype, etype, vtype, with_edge_id=False):
    """Internal function to create a graph from a scipy sparse matrix with types.

    Parameters
    ----------
    spmat : scipy.sparse.spmatrix
        The adjacency matrix whose rows represent sources and columns
        represent destinations.
    utype : str
        Source node type name.
    etype : str
        Edge type name.
    vtype : str
        Destination node type name.
    with_edge_id : bool
        If True, the entries in the sparse matrix are treated as edge IDs.
        Otherwise, the entries are ignored and edges will be added in
        (source, destination) order.

    Returns
    -------
    DGLHeteroGraph
    """
    num_src, num_dst = spmat.shape
    num_ntypes = 1 if utype == vtype else 2
    if spmat.getformat() == 'coo':
        row = utils.toindex(spmat.row)
        col = utils.toindex(spmat.col)
        hgidx = heterograph_index.create_unitgraph_from_coo(
            num_ntypes, num_src, num_dst, row, col)
    else:
        spmat = spmat.tocsr()
        indptr = utils.toindex(spmat.indptr)
        indices = utils.toindex(spmat.indices)
        # TODO(minjie): with_edge_id is only reasonable for csr matrix. How to fix?
        data = utils.toindex(spmat.data if with_edge_id else list(range(len(indices))))
        hgidx = heterograph_index.create_unitgraph_from_csr(
            num_ntypes, num_src, num_dst, indptr, indices, data)
    if num_ntypes == 1:
        return DGLHeteroGraph(hgidx, [utype], [etype])
    else:
        return DGLHeteroGraph(hgidx, [utype, vtype], [etype])

def create_from_networkx(nx_graph,
                         ntype, etype,
                         edge_id_attr_name='id',
                         node_attrs=None,
                         edge_attrs=None):
    """Create graph that has only one set of nodes and edges.
    """
    if not nx_graph.is_directed():
        nx_graph = nx_graph.to_directed()

    # Relabel nodes using consecutive integers
    nx_graph = nx.convert_node_labels_to_integers(nx_graph, ordering='sorted')

    # nx_graph.edges(data=True) returns src, dst, attr_dict
    if nx_graph.number_of_edges() > 0:
        has_edge_id = edge_id_attr_name in next(iter(nx_graph.edges(data=True)))[-1]
    else:
        has_edge_id = False

    if has_edge_id:
        num_edges = nx_graph.number_of_edges()
        src = np.zeros((num_edges,), dtype=np.int64)
        dst = np.zeros((num_edges,), dtype=np.int64)
        for u, v, attr in nx_graph.edges(data=True):
            eid = attr[edge_id_attr_name]
            src[eid] = u
            dst[eid] = v
    else:
        src = []
        dst = []
        for e in nx_graph.edges:
            src.append(e[0])
            dst.append(e[1])
    src = utils.toindex(src)
    dst = utils.toindex(dst)
    num_nodes = nx_graph.number_of_nodes()
    g = create_from_edges(src, dst, ntype, etype, ntype, num_nodes, num_nodes)

    # handle features
    # copy attributes
    def _batcher(lst):
        if F.is_tensor(lst[0]):
            return F.cat([F.unsqueeze(x, 0) for x in lst], dim=0)
        else:
            return F.tensor(lst)
    if node_attrs is not None:
        # mapping from feature name to a list of tensors to be concatenated
        attr_dict = defaultdict(list)
        for nid in range(g.number_of_nodes()):
            for attr in node_attrs:
                attr_dict[attr].append(nx_graph.nodes[nid][attr])
        for attr in node_attrs:
            g.ndata[attr] = _batcher(attr_dict[attr])

    if edge_attrs is not None:
        # mapping from feature name to a list of tensors to be concatenated
        attr_dict = defaultdict(lambda: [None] * g.number_of_edges())
        # each defaultdict value is initialized to be a list of None
        # None here serves as placeholder to be replaced by feature with
        # corresponding edge id
        if has_edge_id:
            num_edges = g.number_of_edges()
            for _, _, attrs in nx_graph.edges(data=True):
                if attrs[edge_id_attr_name] >= num_edges:
                    raise DGLError('Expect the pre-specified edge ids to be'
                                   ' smaller than the number of edges --'
                                   ' {}, got {}.'.format(num_edges, attrs['id']))
                for key in edge_attrs:
                    attr_dict[key][attrs['id']] = attrs[key]
        else:
            # XXX: assuming networkx iteration order is deterministic
            #      so the order is the same as graph_index.from_networkx
            for eid, (_, _, attrs) in enumerate(nx_graph.edges(data=True)):
                for key in edge_attrs:
                    attr_dict[key][eid] = attrs[key]
        for attr in edge_attrs:
            for val in attr_dict[attr]:
                if val is None:
                    raise DGLError('Not all edges have attribute {}.'.format(attr))
            g.edata[attr] = _batcher(attr_dict[attr])

    return g

def create_from_networkx_bipartite(nx_graph,
                                   utype, etype, vtype,
                                   edge_id_attr_name='id',
                                   node_attrs=None,
                                   edge_attrs=None):
    """Create graph that has only one set of nodes and edges.

    The input graph must follow the bipartite graph convention of networkx.
    Each node has an attribute ``bipartite`` with values 0 and 1 indicating which
    set it belongs to.

    Only edges from node set 0 to node set 1 are added to the returned graph.
    """
    if not nx_graph.is_directed():
        nx_graph = nx_graph.to_directed()

    top_nodes = {n for n, d in nx_graph.nodes(data=True) if d['bipartite'] == 0}
    bottom_nodes = set(nx_graph) - top_nodes
    top_nodes = sorted(top_nodes)
    bottom_nodes = sorted(bottom_nodes)
    top_map = {n : i for i, n in enumerate(top_nodes)}
    bottom_map = {n : i for i, n in enumerate(bottom_nodes)}

    if nx_graph.number_of_edges() > 0:
        has_edge_id = edge_id_attr_name in next(iter(nx_graph.edges(data=True)))[-1]
    else:
        has_edge_id = False

    if has_edge_id:
        num_edges = nx_graph.number_of_edges()
        src = np.zeros((num_edges,), dtype=np.int64)
        dst = np.zeros((num_edges,), dtype=np.int64)
        for u, v, attr in nx_graph.edges(data=True):
            eid = attr[edge_id_attr_name]
            src[eid] = top_map[u]
            dst[eid] = bottom_map[v]
    else:
        src = []
        dst = []
        for e in nx_graph.edges:
            if e[0] in top_map:
                src.append(top_map[e[0]])
                dst.append(bottom_map[e[1]])
    src = utils.toindex(src)
    dst = utils.toindex(dst)
    g = create_from_edges(src, dst, utype, etype, vtype, len(top_nodes), len(bottom_nodes))

    # TODO attributes
    assert node_attrs is None
    assert edge_attrs is None
    return g

def to_networkx(g, node_attrs=None, edge_attrs=None):
    """Convert to networkx graph.

    See Also
    --------
    DGLHeteroGraph.to_networkx
    """
    return g.to_networkx(node_attrs, edge_attrs)
