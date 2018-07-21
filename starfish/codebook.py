import json
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import validators
import xarray as xr
from sklearn.neighbors import NearestNeighbors

from starfish.constants import Indices, AugmentedEnum
from starfish.intensity_table import IntensityTable
from starfish.typing import Number


class Codebook(xr.DataArray):
    """Codebook for an image-based transcriptomics experiment

    The codebook is a three dimensional tensor whose values are the expected intensity of a spot
    for each code in each hybridization round and each color channel. This class supports the
    construction of synthetic codebooks for testing, and exposes decode methods to assign gene
    identifiers to spots. This codebook provides an in-memory representation of the codebook
    defined in the spaceTx format.

    The codebook is a subclass of xarray, and exposes the complete public API of that package in
    addition to the methods and constructors listed below.

    Constructors
    ------------
    from_code_array(code_array, n_hyb, n_ch)
        construct a codebook from a spaceTx-spec array of codewords
    from_json(json_codebook, n_hyb, n_ch)
        load a codebook from a spaceTx spec-compliant json file
    synthetic_one_hot_codebook
        Construct a codebook of random codes where only one channel is on per hybridization round.
        This is the typical codebook format for in-situ sequencing and non-multiplex smFISH
        experiments.

    Methods
    -------
    decode_euclidean(intensities)
        find the closest code for each spot in intensities by euclidean distance
    decode_per_channel_maximum(intensities)
        find codes that match the per-channel max intensity for each spot in intensities
    code_length()
        return the total length of the codes in the codebook

    Attributes
    ----------
    Constants.CODEWORD
        name of codeword field in spaceTx spec
    Constants.GENE
        name of gene specifier in spaceTx spec
    Constants.VALUE
        name of value specifier in SpaceTx spec

    Examples
    --------

    >>> from starfish.util.synthesize import SyntheticData
    >>> sd = SyntheticData(n_ch=3, n_hyb=4, n_codes=2)
    >>> sd.codebook()
    <xarray.Codebook (gene_name: 2, c: 3, h: 4)>
    array([[[0, 0, 0, 0],
            [0, 0, 1, 1],
            [1, 1, 0, 0]],

           [[1, 0, 0, 0],
            [0, 0, 1, 0],
            [0, 1, 0, 1]]], dtype=uint8)
    Coordinates:
      * gene_name  (gene_name) object 08b1a822-a1b4-4e06-81ea-8a4bd2b004a9 ...
      * c          (c) int64 0 1 2
      * h          (h) int64 0 1 2 3

    See Also
    --------
    TODO <link to spaceTx format>

    """

    class Constants(AugmentedEnum):
        CODEWORD = 'codeword'
        GENE = 'gene_name'
        VALUE = 'v'

    @property
    def code_length(self) -> int:
        """return the length of codes in this codebook"""
        return int(np.dot(*self.shape[1:]))

    @classmethod
    def _empty_codebook(cls, code_names: Sequence[str], n_ch: int, n_hyb: int):
        """create an empty codebook of shape (code_names, n_ch, n_hyb)

        Parameters
        ----------
        code_names : Sequence[str]
            the genes to be coded
        n_ch : int
            number of channels used to build the codes
        n_hyb : int
            number of hybridization rounds used to build the codes

        Examples
        --------
        >>> from starfish.codebook import Codebook
        >>> Codebook._empty_codebook(['ACTA', 'ACTB'], n_ch=3, n_hyb=2)
        <xarray.Codebook (gene_name: 2, c: 3, h: 2)>
        array([[[0, 0],
                [0, 0],
                [0, 0]],

               [[0, 0],
                [0, 0],
                [0, 0]]], dtype=uint8)
        Coordinates:
          * gene_name  (gene_name) object 'ACTA' 'ACTB'
          * c          (c) int64 0 1 2
          * h          (h) int64 0 1

        Returns
        -------
        Codebook :
            codebook whose values are all zero

        """
        codes_index = pd.Index(code_names, name=Codebook.Constants.GENE.value)
        return cls(
            data=np.zeros((codes_index.shape[0], n_ch, n_hyb), dtype=np.uint8),
            coords=(
                codes_index,
                pd.Index(np.arange(n_ch), name=Indices.CH.value),
                pd.Index(np.arange(n_hyb), name=Indices.HYB.value),
            )
        )

    @classmethod
    def from_code_array(
            cls, code_array: List[Dict[Union[str, Constants], Any]],
            n_hyb: Optional[int]=None, n_ch: Optional[int]=None) -> "Codebook":
        """construct a codebook from a spaceTx-spec array of codewords

        Parameters
        ----------
        code_array : List[Dict[str, Any]]
            Array of dictionaries, each containing a codeword and gene_name
        n_hyb : Optional[int]
            The number of hybridization rounds used in the codes. Will be inferred if not provided
        n_ch : Optional[int]
            The number of channels used in the codes. Will be inferred if not provided

        Examples
        --------

        >>> from starfish.constants import Indices
        >>> from starfish.codebook import Codebook
        >>> import tempfile
        >>> import json
        >>> import os
        >>> dir_ = tempfile.mkdtemp()

        >>> codebook = [
        >>>     {
        >>>         Codebook.Constants.CODEWORD.value: [
        >>>             {Indices.HYB.value: 0, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>             {Indices.HYB.value: 1, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>         ],
        >>>         Codebook.Constants.GENE.value: "ACTB_human"
        >>>     },
        >>>     {
        >>>         Codebook.Constants.CODEWORD.value: [
        >>>             {Indices.HYB.value: 0, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>             {Indices.HYB.value: 1, Indices.CH.value: 1, Codebook.Constants.VALUE.value: 1},
        >>>         ],
        >>>         Codebook.Constants.GENE.value: "ACTB_mouse"
        >>>     },
        >>> ]

        >>> json_codebook = os.path.join(dir_, 'codebook.json')
        >>> with open(json_codebook, 'w') as f:
        >>>     json.dump(codebook, f)
        <xarray.Codebook (gene_name: 2, c: 4, h: 2)>
        array([[[0, 0],
                [0, 0],
                [0, 0],
                [1, 1]],

               [[0, 0],
                [0, 1],
                [0, 0],
                [1, 0]]], dtype=uint8)
        Coordinates:
          * gene_name  (gene_name) object 'ACTB_human' 'ACTB_mouse'
          * c          (c) int64 0 1 2 3
          * h          (h) int64 0 1

        Codebook.from_json(json_codebook)

        Returns
        -------
        Codebook :
            Codebook with shape (genes, channels, hybridization_rounds)

        """

        # guess the max hyb and channel if not provided, otherwise check provided values are valid
        max_hyb, max_ch = 0, 0

        for code in code_array:
            for entry in code[Codebook.Constants.CODEWORD]:
                max_hyb = max(max_hyb, entry[Indices.HYB])
                max_ch = max(max_ch, entry[Indices.CH])

        # set n_ch and n_hyb if either were not provided
        n_hyb = n_hyb if n_hyb is not None else max_hyb + 1
        n_ch = n_ch if n_ch is not None else max_ch + 1

        # raise errors if provided n_hyb or n_ch are out of range
        if max_hyb + 1 > n_hyb:
            raise ValueError(
                f'code detected that requires a hybridization value ({max_hyb + 1}) that is '
                f'greater than provided n_hyb: {n_hyb}')
        if max_ch + 1 > n_ch:
            raise ValueError(
                f'code detected that requires a channel value ({max_ch + 1}) that is greater '
                f'than provided n_hyb: {n_ch}')

        # verify codebook structure and fields
        for code in code_array:

            if not isinstance(code, dict):
                raise ValueError(f'codebook must be an array of dictionary codes. Found: {code}.')

            # verify all necessary fields are present
            required_fields = {Codebook.Constants.CODEWORD, Codebook.Constants.GENE}
            missing_fields = required_fields.difference(code)
            if missing_fields:
                raise ValueError(
                    f'Each entry of codebook must contain {required_fields}. Missing fields: '
                    f'{missing_fields}')

        gene_names = [w[Codebook.Constants.GENE] for w in code_array]
        code_data = cls._empty_codebook(gene_names, n_ch, n_hyb)

        # fill the codebook
        for code_dict in code_array:
            codeword = code_dict[Codebook.Constants.CODEWORD]
            gene = code_dict[Codebook.Constants.GENE]
            for entry in codeword:
                code_data.loc[gene, entry[Indices.CH], entry[Indices.HYB]] = entry[
                    Codebook.Constants.VALUE]

        return code_data

    @classmethod
    def from_json(
            cls, json_codebook: str, n_hyb: Optional[int]=None, n_ch: Optional[int]=None
    ) -> "Codebook":
        """Load a codebook from a spaceTx spec-compliant json file or a url pointing to such a file

        Parameters
        ----------
        json_codebook : str
            path or url to json file containing a spaceTx codebook
        n_hyb : Optional[int]
            The number of hybridization rounds used in the codes. Will be inferred if not provided
        n_ch : Optional[int]
            The number of channels used in the codes. Will be inferred if not provided

        Examples
        --------
        >>> from starfish.constants import Indices
        >>> from starfish.codebook import Codebook

        >>> codebook = [
        >>>     {
        >>>         Codebook.Constants.CODEWORD.value: [
        >>>             {Indices.HYB.value: 0, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>             {Indices.HYB.value: 1, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>         ],
        >>>         Codebook.Constants.GENE.value: "ACTB_human"
        >>>     },
        >>>     {
        >>>         Codebook.Constants.CODEWORD.value: [
        >>>             {Indices.HYB.value: 0, Indices.CH.value: 3, Codebook.Constants.VALUE.value: 1},
        >>>             {Indices.HYB.value: 1, Indices.CH.value: 1, Codebook.Constants.VALUE.value: 1},
        >>>         ],
        >>>         Codebook.Constants.GENE.value: "ACTB_mouse"
        >>>     },
        >>> ]

        >>> Codebook.from_json(codebook)
       <xarray.Codebook (gene_name: 2, c: 4, h: 2)>
        array([[[0, 0],
                [0, 0],
                [0, 0],
                [1, 1]],

               [[0, 0],
                [0, 1],
                [0, 0],
                [1, 0]]], dtype=uint8)
        Coordinates:
          * gene_name  (gene_name) object 'ACTB_human' 'ACTB_mouse'
          * c          (c) int64 0 1 2 3
          * h          (h) int64 0 1

        Returns
        -------
        Codebook :
            Codebook with shape (genes, channels, hybridization_rounds)

        """
        if validators.url(json_codebook):
            with urllib.request.urlopen(json_codebook) as response:
                code_array = json.loads(response.read().decode('utf-8'))
        else:
            with open(json_codebook, 'r') as f:
                code_array = json.load(f)
        return cls.from_code_array(code_array, n_hyb, n_ch)

    def to_json(self, filename: str) -> None:
        """save a codebook to json

        Notes
        -----
        This enforces the following typing of codebooks:
        ch, hyb: int
        value: float
        gene: str

        Parameters
        ----------
        filename : str
            filename

        """
        code_array = []
        for gene in self[self.Constants.GENE.value]:
            codeword = []
            for ch in self[Indices.CH.value]:
                for hyb in self[Indices.HYB.value]:
                    if self.loc[gene, ch, hyb]:
                        codeword.append(
                            {
                                Indices.CH.value: int(ch),
                                Indices.HYB.value: int(hyb),
                                self.Constants.VALUE.value: float(self.loc[gene, ch, hyb])
                            })
            code_array.append({
                self.Constants.CODEWORD.value: codeword,
                self.Constants.GENE.value: str(gene.values)
            })

        with open(filename, 'w') as f:
            json.dump(code_array, f)

    @staticmethod
    def _normalize_features(array: Union["Codebook", IntensityTable], norm_order) \
            -> Tuple[Union["Codebook", IntensityTable], np.ndarray]:
        """unit normalize each feature of array

        Parameters
        ----------
        array : Union[Codebook, IntensityTable]
            codebook or intensity table containing (ch, r) features to normalize
        norm_order : int
            the norm to apply to each feature

        See Also
        --------
        The available norms for this function can be found at the following link:
        https://docs.scipy.org/doc/numpy-1.14.0/reference/generated/numpy.linalg.norm.html

        Returns
        -------
        Union[IntensityTable, Codebook] :
            IntensityTable or Codebook containing normalized features
        np.ndarray :
            A 1 dimensional numpy array containing the feature norms

        """
        feature_traces = array.stack(traces=(Indices.CH.value, Indices.HYB.value))
        norm = np.linalg.norm(feature_traces.values, ord=norm_order, axis=1)
        array = array / norm[:, None, None]

        # if a feature is all zero, the information should be spread across the channel
        n = array.sizes[Indices.CH.value] * array.sizes[Indices.HYB.value]
        partitioned_intensity = np.linalg.norm(np.full(n, fill_value=1 / n), ord=norm_order) / n
        array = array.fillna(partitioned_intensity)

        return array, norm

    @staticmethod
    def _approximate_nearest_code(
            norm_codes: "Codebook", norm_intensities: xr.DataArray, metric: str,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """find the nearest code for each feature using the ball_tree approximate NN algorithm

        Parameters
        ----------
        norm_codes : Codebook
            codebook with each code normalized to unit length (sum = 1)
        norm_intensities : IntensityTable
            intensity table with each feature normalized to unit length (sum = 1)
        metric : str
            the sklearn metric string to pass to NearestNeighbors

        Returns
        -------
        np.ndarray : metric_output
            the output of metric applied to each feature closest code
        np.ndarray : gene_ids
            the gene that corresponds to each matched code

        """
        # TODO ambrosejcarr: see if features can be pre-masked to reduce NN calculations
        linear_codes = norm_codes.stack(traces=(Indices.CH.value, Indices.HYB.value)).values
        linear_features = norm_intensities.stack(
            traces=(Indices.CH.value, Indices.HYB.value)).values

        # reshape into traces
        nn = NearestNeighbors(n_neighbors=1, algorithm='ball_tree', metric=metric).fit(linear_codes)
        metric_output, indices = nn.kneighbors(linear_features)
        gene_ids = np.ravel(norm_codes.indexes[Codebook.Constants.GENE.value].values[indices])

        return np.ravel(metric_output), gene_ids

    def metric_decode(
            self, intensities: IntensityTable, max_distance: Number, min_intensity: Number,
            norm: int, metric: str='euclidean'
    ) -> IntensityTable:
        """Assign the closest gene by euclidean distance to each feature in an intensity table

        Normalizes both the codes and the features to be unit vectors and finds the closest code
        for each feature

        Parameters
        ----------
        intensities : IntensityTable
            features to be decoded
        max_distance : Number
            maximum distance between a feature and its closest code for which the coded gene will
            be assigned.
        min_intensity : Number
            minimum intensity for a feature to receive a gene id
        norm : int
            the scipy.linalg norm to apply to normalize codes and intensities
        metric : str
            the sklearn metric string to pass to NearestNeighbors

        See Also
        --------
        The available norms for this function can be found at the following link:
        https://docs.scipy.org/doc/numpy-1.14.0/reference/generated/numpy.linalg.norm.html

        Returns
        -------
        IntensityTable :
            intensity table containing additional data variables for gene assignments and metric
            outputs

        """
        # normalize both the intensities and the codebook
        norm_intensities, norms = self._normalize_features(intensities, norm_order=norm)
        norm_codes, _ = self._normalize_features(self, norm_order=norm)

        # mask low intensity features
        intensity_mask = np.where(norms < min_intensity)[0]

        metric_outputs, gene_ids = self._approximate_nearest_code(
            norm_codes, norm_intensities, metric=metric)

        exceeds_distance = np.where(metric_outputs > max_distance)[0]
        gene_index = pd.Index(gene_ids)

        # remove genes associated with distant codes
        gene_index.values[exceeds_distance] = 'None'
        gene_index.values[intensity_mask] = 'None'

        # set new values on the intensity table in-place
        intensities[IntensityTable.Constants.GENE.value] = (
            IntensityTable.Constants.FEATURES.value, gene_index)
        intensities[IntensityTable.Constants.DISTANCE.value] = (
            IntensityTable.Constants.FEATURES.value, metric_outputs)

        return intensities

    def decode_per_hyb_max(self, intensities: IntensityTable) -> IntensityTable:
        """decode each feature by selecting the per-hybridization round max-valued channel

        Notes
        -----
        If no code matches the per-channel max of a feature, it will be assigned 'None' instead
        of a gene value

        Parameters
        ----------
        intensities : IntensityTable
            features to be decoded

        Returns
        -------
        IntensityTable :
            intensity table containing additional data variables for gene assignments

        """

        def _view_row_as_element(array: np.ndarray) -> np.ndarray:
            """view an entire code as a single element

            This view allows vectors (codes) to be compared for equality without need for multiple
            comparisons by casting the data in each code to a structured dtype that registers as
            a single value

            Parameters
            ----------
            array : np.ndarray
                2-dimensional numpy array of shape (n_observations, (n_ch * n_hyb)) where
                observations may be either features or codes.

            Returns
            -------
            np.ndarray :
                1-dimensional vector of shape n_observations

            """
            nrows, ncols = array.shape
            dtype = {'names': ['f{}'.format(i) for i in range(ncols)],
                     'formats': ncols * [array.dtype]}
            return array.view(dtype)

        max_channels = intensities.argmax(Indices.CH.value)
        codes = self.argmax(Indices.CH.value)

        a = _view_row_as_element(codes.values.reshape(self.shape[0], -1))
        b = _view_row_as_element(max_channels.values.reshape(intensities.shape[0], -1))

        # TODO ambrosejcarr: the object makes working with the data awkward
        # we could store a map between genes and ints as an `attr`, and use that to convert
        # for the public API.
        genes = np.empty(intensities.shape[0], dtype=object)
        genes.fill("None")

        for i in np.arange(a.shape[0]):
            genes[np.where(a[i] == b)[0]] = codes['gene_name'][i]
        gene_index = pd.Index(genes.astype('U'))

        intensities[IntensityTable.Constants.GENE.value] = (
            IntensityTable.Constants.FEATURES.value, gene_index)

        return intensities

    @classmethod
    def synthetic_one_hot_codebook(
            cls, n_hyb: int, n_channel: int, n_codes: int, gene_names: Optional[Sequence]=None
    ) -> "Codebook":
        """Generate codes where one channel is "on" in each hybridization round

        Parameters
        ----------
        n_hyb : int
            number of hybridization rounds per code
        n_channel : int
            number of channels per code
        n_codes : int
            number of codes to generate
        gene_names : Optional[List[str]]
            if provided, names for genes in codebook

        Examples
        --------
        >>> from starfish.codebook import Codebook

        >>> Codebook.synthetic_one_hot_codebook(n_hyb=2, n_channel=3, n_codes=2)
        <xarray.Codebook (gene_name: 2, c: 3, h: 2)>
        array([[[0, 1],
                [0, 0],
                [1, 0]],

               [[1, 1],
                [0, 0],
                [0, 0]]], dtype=uint8)
        Coordinates:
          * gene_name  (gene_name) object b25180dc-8af5-48f1-bff4-b5649683516d ...
          * c          (c) int64 0 1 2
          * h          (h) int64 0 1

        Returns
        -------
        List[Dict] :
            list of codewords

        """

        # TODO ambrosejcarr: clean up this code, generate Codebooks directly using _empty_codebook
        # construct codes; this can be slow when n_codes is large and n_codes ~= n_possible_codes
        codes: Set = set()
        while len(codes) < n_codes:
            codes.add(tuple([np.random.randint(0, n_channel) for _ in np.arange(n_hyb)]))

        # construct codewords from code
        codewords = [
            [
                {
                    Indices.HYB.value: h, Indices.CH.value: c, 'v': 1
                } for h, c in enumerate(code)
            ] for code in codes
        ]

        # make a codebook from codewords
        if gene_names is None:
            # use a reverse-sorted list of integers as codewords
            gene_names = [uuid.uuid4() for _ in range(n_codes)]
        assert n_codes == len(gene_names)

        codebook = [{Codebook.Constants.CODEWORD.value: w, Codebook.Constants.GENE.value: g}
                    for w, g in zip(codewords, gene_names)]

        return cls.from_code_array(codebook, n_hyb=n_hyb, n_ch=n_channel)