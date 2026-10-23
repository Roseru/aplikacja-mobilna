package pl.roseru.kalorie.ui

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import pl.roseru.kalorie.catalogupdate.CatalogUpdateFactory
import pl.roseru.kalorie.catalogupdate.CatalogUpdateViewModel
import pl.roseru.kalorie.core.network.DeviceNetworkPolicy
import pl.roseru.kalorie.core.network.NetworkPolicyViewModel
import pl.roseru.kalorie.data.CalorieDatabase

class DeviceNetworkModels(val catalog:CatalogUpdateViewModel,val policy:NetworkPolicyViewModel)

/** Explicit activity owner keeps device data separate from account-specific diary stores. */
@Composable fun rememberDeviceNetworkModels(owner:ViewModelStoreOwner,context:Context,database:CalorieDatabase,
    policy:DeviceNetworkPolicy):DeviceNetworkModels {
    val catalog:CatalogUpdateViewModel=viewModel(viewModelStoreOwner=owner,key="device:catalog-update",factory=viewModelFactory {
        initializer {CatalogUpdateViewModel(CatalogUpdateFactory.repository(context,database,policy))}
    })
    val network:NetworkPolicyViewModel=viewModel(viewModelStoreOwner=owner,key="device:network-policy",factory=viewModelFactory {
        initializer {NetworkPolicyViewModel(policy)}
    })
    return DeviceNetworkModels(catalog,network)
}
