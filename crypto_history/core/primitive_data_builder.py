import logging
import pandas as pd
import xarray as xr
from dataclasses import dataclass, fields, asdict
from typing import Union, List
from datetime import datetime
from .tickers import TickerPool
from .get_market_data import StockMarketFactory
from ..utilities import general_utilities, exceptions

logger = logging.getLogger(__name__)


class PrimitiveCoinHistoryObtainer:
    """Abstract class to serve as the parent to generating histories obtainer classes"""
    def __init__(self,
                 exchange_factory: StockMarketFactory,
                 interval: str,
                 start_str: Union[str, datetime],
                 end_str: Union[str, datetime],
                 limit: int):
        """
        Generates the coin history obtainer

        Args:
            exchange_factory(StockMarketFactory): instance of the exchange_factory which is responsible for \
            setting the market_homogenizer
            interval(str): Length of the history of the klines per item
            start_str(str|datetime): duration from which history is necessary
            end_str(str|datetime): duration upto which history is necessary
            limit(int): number of klines required maximum. Note that it is limited by 1000 by binance
        """
        assert limit <= 1000, f"Binance will not accept intervals greater than 1000. Reduce it!"
        self.market_requester = exchange_factory.create_market_requester()
        self.market_operations = exchange_factory.create_market_operations(self.market_requester)
        self.market_harmonizer = exchange_factory.create_data_homogenizer(self.market_operations)
        self.data_container = None
        self.interval = interval
        self.start_str = start_str
        self.end_str = end_str
        self.limit = limit
        self.ticker_pool = None
        self.example_raw_history = None

    async def initialize_example(self):
        """
        Initializes an example of the raw history and stores it example_raw_history

        Returns:
             list: instance of an example of a raw history of ETHvsBTC

        """
        self.example_raw_history = self.example_raw_history or list(await self._get_raw_history_for_ticker("ETHBTC"))
        return self.example_raw_history

    async def _get_raw_history_for_ticker(self, ticker_symbol: str) -> map:
        """
        Gets the raw history for the ticker by using the interface to the market provided by the market homogenizer

        Args:
            ticker_symbol(str): Symbol of the ticker whose history is desired

        Returns:
             map: raw mapped history of the ticker mapped to the OHLCVFields instance

        """
        return await self.market_harmonizer.get_history_for_ticker(ticker=ticker_symbol,
                                                                   interval=self.interval,
                                                                   start_str=self.start_str,
                                                                   end_str=self.end_str,
                                                                   limit=self.limit)

    async def get_all_raw_tickers(self) -> TickerPool:
        """
        Obtains the ticker pool by accessing the market homogenizer

        Returns:
             TickerPool: The TickerPool filled with all the ticker available to the market/exchange

        """
        return await self.market_harmonizer.get_all_raw_tickers()

    async def get_historical_data_relevant_coins_from_base_and_reference_assets(self, base_assets, reference_assets):
        """
        Get the historical data for the combination of base and reference assets
        Args:
            base_assets (List['str']): list of all base assets
            reference_assets (List['str']): list of all reference assets

        Returns:
            The kline historical data of the combinations
        """
        raw_ticker_pool = await self.get_all_raw_tickers()
        tickers_to_capture = []
        for base_asset in base_assets:
            for reference_asset in reference_assets:
                if any(f"{base_asset}{reference_asset}" == raw_ticker["symbol"] for raw_ticker in raw_ticker_pool):
                    tickers_to_capture.append((base_asset, reference_asset))
        return await self._get_historical_data_relevant_coins(tickers_to_capture)

    async def _get_historical_data_relevant_coins(self, tickers_to_capture: List[tuple]):
        """
        Get the history of all the tickers in the market/exchange

        Args:
            tickers_to_capture (list): List of tickers to capture

        Returns:
             map: map of all the histories in the exchange/market
             mapped from history to the OHLCVFields

        """
        tasks_to_pursue = {}
        for base_asset, reference_asset in tickers_to_capture:
            tasks_to_pursue[base_asset, reference_asset] = \
                self._get_raw_history_for_ticker(f"{base_asset}{reference_asset}")
        return await general_utilities.gather_dict(tasks_to_pursue)

    """The x-array's coin-history obtainer class"""
    async def get_all_historical_data(self):
        """Obtains the historical data of all the combinations"""
        return await self._get_historical_data_relevant_coins(tickers_to_capture=self.ticker_pool)


class PrimitiveDimensionsManager:
    """Class responsible for managing the dimensions/coordinates of the data container"""

    @dataclass
    class Dimensions:
        """Class for keeping track of the dimensions of the XDataArray"""
        base_assets: List
        reference_assets: List
        ohlcv_fields: List
        index_number: List

    def __init__(self, history_obtainer):
        """Initializes the dimensions manager with the coin_history_obtainer"""
        self.coin_history_obtainer = history_obtainer

    async def get_depth_of_indices(self):
        """
        Obtains the depth of the indices to identify how many time-stamp values
         each history has available

        Returns:
             list: The list of indices from 0..n-1
                     where n corresponds to the number of time-stamps in the history

        """
        example_history = await self.coin_history_obtainer.initialize_example()
        indices = list(range(len(list(example_history))))
        return indices

    @staticmethod
    async def set_coords_dimensions_in_empty_container(dataclass_dimensions_coordinates) -> xr.DataArray:
        """
        Initialize the xarray container with None values but with the coordinates
        as it helps in the memory allocation
        Args:
            dataclass_dimensions_coordinates: dataclass of coordinates/dimensions as the framework for generating \
            the XDataArray
        """
        dimensions = [dimension.name for dimension in fields(dataclass_dimensions_coordinates)]
        coordinates = [getattr(dataclass_dimensions_coordinates, item) for item in dimensions]
        return xr.DataArray(None, coords=coordinates, dims=dimensions)

    async def get_dimension_coordinates_from_fields_and_assets(self,
                                                               ohlcv_fields,
                                                               base_assets,
                                                               reference_assets):

        index_number = await self.get_depth_of_indices()
        ohlcv_fields.append("weight")
        return self.Dimensions(
            base_assets=base_assets,
            reference_assets=reference_assets,
            ohlcv_fields=ohlcv_fields,
            index_number=index_number)


class PrimitiveDataContainerOperations:
    """Abstract Base Class for generating the data operations"""

    def __init__(self,
                 exchange_factory,
                 base_assets,
                 reference_assets,
                 ohlcv_fields,
                 interval,
                 start_str,
                 end_str,
                 limit):
        """
        Initialize the data container operations

        Args:
            history_obtainer: instance of the history obtainer
            dimensions_manager: instance of the responsible class instance for managing dimensions/coordinates
        """
        self.history_obtainer = PrimitiveCoinHistoryObtainer(exchange_factory,
                                                             interval,
                                                             start_str,
                                                             end_str,
                                                             limit)
        self.dimension_manager = PrimitiveDimensionsManager(self.history_obtainer)
        self.base_assets = base_assets
        self.reference_assets = reference_assets
        self.ohlcv_fields = ohlcv_fields
        self.interval = interval

    @staticmethod
    def drop_unnecessary_columns_from_df(df, necessary_columns):
        """
        Drop all columns which are not necessary from the df
        Args:
            df (pd.DataFrame): from which the unnecessary columns are to be dropped
            necessary_columns (list): list of columns which are to be stored

        Returns:
            pd.DataFrame where the unnecessary columns are dropped
        """
        unnecessary_columns = [col for col in df.columns if col not in necessary_columns]
        return df.drop(unnecessary_columns, axis=1)

    async def get_populated_primitive_container(self):
        """
        Populates the container and returns it to the use

        Args:
            ohlcv_fields (list): list of OHLCV fields needed finally
            base_assets (list): list of base assets
            reference_assets (list): list of reference assets
        Returns:
             xr.DataArray: the filled container of information

        """
        # TODO Avoid populating it every time it is called
        coord_dimension_dataclass = await self.dimension_manager.get_dimension_coordinates_from_fields_and_assets(
            ohlcv_fields=self.ohlcv_fields,
            base_assets=self.base_assets,
            reference_assets=self.reference_assets,
        )

        data_container = await self.dimension_manager.set_coords_dimensions_in_empty_container(
            coord_dimension_dataclass
        )
        data_container = await self.populate_container(data_container, coord_dimension_dataclass)
        return data_container

    @staticmethod
    def _insert_coin_history_in_container(data_container, base_asset, reference_asset, history_df):
        """
        Low level function to inserts the coin history in the df
        Args:
            base_asset (str): base asset of the coin
            reference_asset (str): reference asset of the coin
            history_df (pd.DataFrame): data frame of the coin history

        Returns:
            None
        """
        logger.debug(f"History set in x_array for ticker {base_asset}{reference_asset}")
        data_container.loc[base_asset, reference_asset] = history_df.transpose()
        return data_container

    @staticmethod
    def append_weight_column_to_df(df, column_name, column_value):
        df[column_name] = column_value
        return df

    async def populate_container(self, data_container,  coord_dimension_dataclass):
        """
        Populates the xarray.DataArray with the historical data of all the coins
        """
        historical_data = await self.history_obtainer.get_historical_data_relevant_coins_from_base_and_reference_assets(
            base_assets=coord_dimension_dataclass.base_assets,
            reference_assets=coord_dimension_dataclass.reference_assets
        )
        for (base_asset, reference_asset), ticker_raw_history in historical_data.items():
            try:
                history_df = await self.get_compatible_df(ticker_raw_history)
            except exceptions.EmptyDataFrameException:
                logger.debug(f"History does not exist for the combination of {base_asset}{reference_asset}")
                continue
            else:
                history_df = self.drop_unnecessary_columns_from_df(history_df, coord_dimension_dataclass.ohlcv_fields)
                history_df = self.append_weight_column_to_df(history_df, "weight", self.interval)
            data_container = self._insert_coin_history_in_container(
                data_container,
                base_asset,
                reference_asset,
                history_df)
        return data_container

    @staticmethod
    def calculate_rows_to_add(df, list_of_standard_history) -> int:
        """
        Calculates the additional number of rows that might have to be added to get the df in the same shape

        Args:
            df(pd.DataFrame): pandas dataframe which is obtained for the coin's history
            list_of_standard_history: expected standard history which has the complete history

        Returns:
             int: number of rows that have to be added to the df

        """
        df_rows, _ = df.shape
        expected_rows = len(list_of_standard_history)
        return expected_rows - df_rows

    async def pad_extra_rows_if_necessary(self, history_df):
        """
        Add extra rows on the bottom of the DF is necessary. i.e when the history is incomplete.
        # FixMe . Probably needs to be reevaluated
        Args:
            history_df: history of the dataframe that has not been padded yet

        Returns:
            pd.DataFrame: that has been padded

        """
        await self.history_obtainer.initialize_example()
        rows_to_add = self.calculate_rows_to_add(history_df, self.history_obtainer.example_raw_history)
        if rows_to_add > 0:
            history_df = self.add_extra_rows_to_bottom(history_df, rows_to_add)
        return history_df

    async def get_compatible_df(self, ticker_history):
        """
        Makes the ticker history compatible to the standard pd.DataFrame by extending the
        shape to add null values

        Args:
            ticker_history: history of the current ticker

        Returns:
             pd.DataFrame: compatible history of the df adjusted for same rows as expected

        """
        # TODO Assuming that the df is only not filled in the bottom
        history_df = pd.DataFrame(ticker_history)
        if history_df.empty:
            raise exceptions.EmptyDataFrameException
        padded_df = await self.pad_extra_rows_if_necessary(history_df)
        return padded_df

    @staticmethod
    def add_extra_rows_to_bottom(df: pd.DataFrame, empty_rows_to_add: int):
        """
        Adds extra rows to the pd.DataFrame

        Args:
            df(pd.DataFrame): to which extra rows are to be added
            empty_rows_to_add(int): Number of extra rows that have to be added

        Returns:
             pd.DataFrame: Re-indexed pd.DataFrame which has the compatible number of rows

        """
        new_indices_to_add = list(range(df.index[-1] + 1, df.index[-1] + 1 + empty_rows_to_add))
        return df.reindex(df.index.to_list() + new_indices_to_add)
