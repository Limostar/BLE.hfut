package com.med.bleassistant.ble;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.Intent;
import android.location.LocationManager;
import android.os.Build;
import android.util.Log;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Queue;

/**
 * BLE bridge between Python and the Android Bluetooth stack.
 *
 * NOTE: keep this file ASCII-only on purpose. javac uses the platform default
 * charset when no -encoding is given, so non-ASCII comments can break the build
 * on machines whose default charset is not UTF-8.
 *
 * WHY THIS FILE EXISTS:
 * PyJNIus can only implement Java interfaces; it cannot subclass a Java object.
 * Android's ScanCallback and BluetoothGattCallback are abstract classes, so
 * they cannot be implemented from Python. Both callbacks therefore live here in
 * Java, and the Python side only kicks off actions and polls the static state
 * below. No Java -> Python callback is needed, which also avoids threading
 * problems (BLE callbacks arrive on the Android main thread while Python runs
 * on its own thread).
 *
 * STATE CONTRACT (mirrored by constants in ble_android.py):
 *   scan: 0 idle, 1 running, 2 failed
 *   conn: 0 idle, 1 connecting, 2 connected, 3 disconnected, 4 failed
 */
public final class BleHelper {

    private static final String TAG = "BleHelper";

    public static final int SCAN_IDLE = 0;
    public static final int SCAN_RUNNING = 1;
    public static final int SCAN_FAILED = 2;

    public static final int CONN_IDLE = 0;
    public static final int CONN_CONNECTING = 1;
    public static final int CONN_CONNECTED = 2;
    public static final int CONN_DISCONNECTED = 3;
    public static final int CONN_FAILED = 4;

    private static final Object LOCK = new Object();

    /** address -> "name|address|rssi" */
    private static final Map<String, String> DEVICES = new LinkedHashMap<String, String>();

    private static volatile int scanState = SCAN_IDLE;
    private static volatile int scanError = 0;
    private static volatile int connState = CONN_IDLE;
    private static volatile int connStatus = 0;
    private static volatile int serviceCount = 0;
    private static volatile String connName = "";
    private static volatile String connAddress = "";

    private static BluetoothLeScanner scanner;
    private static boolean scanning = false;
    private static BluetoothGatt gatt;

    private BleHelper() {
    }

    // ------------------------------------------------------------------
    // Adapter / Bluetooth switch
    // ------------------------------------------------------------------
    public static BluetoothAdapter getAdapter(Context ctx) {
        try {
            BluetoothManager manager =
                    (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
            return manager == null ? null : manager.getAdapter();
        } catch (Throwable t) {
            Log.w(TAG, "getAdapter: " + t);
            return null;
        }
    }

    public static boolean isBluetoothEnabled(Context ctx) {
        BluetoothAdapter adapter = getAdapter(ctx);
        return adapter != null && adapter.isEnabled();
    }

    /** Shows the system "turn on Bluetooth" dialog. */
    public static void requestEnable(Context ctx) {
        try {
            Intent intent = new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(intent);
        } catch (Throwable t) {
            Log.w(TAG, "requestEnable: " + t);
        }
    }

    /**
     * Whether the system location switch is on. BLE scan results are suppressed by
     * Android when location services are off, unless BLUETOOTH_SCAN is declared with
     * usesPermissionFlags="neverForLocation". Used for the on-screen diagnostics only.
     */
    public static boolean isLocationEnabled(Context ctx) {
        try {
            LocationManager manager =
                    (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            if (manager == null) {
                return false;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                return manager.isLocationEnabled();
            }
            return manager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                    || manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
        } catch (Throwable t) {
            Log.w(TAG, "isLocationEnabled: " + t);
            return false;
        }
    }

    // ------------------------------------------------------------------
    // BLE scan
    // ------------------------------------------------------------------
    private static final ScanCallback SCAN_CALLBACK = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            addResult(result);
        }

        @Override
        public void onBatchScanResults(List<ScanResult> results) {
            if (results == null) {
                return;
            }
            for (ScanResult result : results) {
                addResult(result);
            }
        }

        @Override
        public void onScanFailed(int errorCode) {
            scanError = errorCode;
            scanState = SCAN_FAILED;
            scanning = false;
        }
    };

    private static void addResult(ScanResult result) {
        if (result == null || result.getDevice() == null) {
            return;
        }
        BluetoothDevice device = result.getDevice();
        String address = device.getAddress();
        if (address == null || address.isEmpty()) {
            return;
        }
        String name = "";
        try {
            String raw = device.getName();
            if (raw != null) {
                name = raw.trim();
            }
        } catch (Throwable ignored) {
            // On Android 12+ reading the name throws unless BLUETOOTH_CONNECT
            // was granted. Missing names are simply left empty.
        }
        synchronized (LOCK) {
            DEVICES.put(address, name + "|" + address + "|" + result.getRssi());
        }
    }

    public static void clearDevices() {
        synchronized (LOCK) {
            DEVICES.clear();
        }
        scanError = 0;
        scanState = SCAN_IDLE;
    }

    /** Returns "name|address|rssi" entries for the Python side to poll. */
    public static String[] getDevices() {
        synchronized (LOCK) {
            return DEVICES.values().toArray(new String[0]);
        }
    }

    public static int getDeviceCount() {
        synchronized (LOCK) {
            return DEVICES.size();
        }
    }

    public static int getScanState() {
        return scanState;
    }

    public static int getScanError() {
        return scanError;
    }

    public static void startScan(Context ctx) {
        stopScan();
        BluetoothAdapter adapter = getAdapter(ctx);
        if (adapter == null) {
            scanError = -1;
            scanState = SCAN_FAILED;
            return;
        }
        if (!adapter.isEnabled()) {
            scanError = -2;
            scanState = SCAN_FAILED;
            return;
        }
        try {
            scanner = adapter.getBluetoothLeScanner();
        } catch (Throwable t) {
            scanner = null;
        }
        if (scanner == null) {
            scanError = -3;
            scanState = SCAN_FAILED;
            return;
        }
        ScanSettings settings = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build();
        try {
            scanner.startScan(null, settings, SCAN_CALLBACK);
            scanning = true;
            scanState = SCAN_RUNNING;
        } catch (Throwable t) {
            Log.w(TAG, "startScan: " + t);
            scanError = -4;
            scanState = SCAN_FAILED;
        }
    }

    public static void stopScan() {
        if (scanner != null && scanning) {
            try {
                scanner.stopScan(SCAN_CALLBACK);
            } catch (Throwable ignored) {
            }
        }
        scanning = false;
        if (scanState == SCAN_RUNNING) {
            scanState = SCAN_IDLE;
        }
    }

    // ------------------------------------------------------------------
    // GATT connection
    // ------------------------------------------------------------------
    private static final BluetoothGattCallback GATT_CALLBACK = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            connStatus = status;
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                connState = CONN_CONNECTED;
                serviceCount = 0;
                try {
                    BluetoothDevice device = g.getDevice();
                    if (device != null) {
                        connAddress = device.getAddress();
                        String raw = device.getName();
                        connName = (raw == null) ? "" : raw.trim();
                    }
                    g.discoverServices();
                } catch (Throwable ignored) {
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                connState = CONN_DISCONNECTED;
                serviceCount = 0;
                // Drop pending commands: otherwise stale commands would be
                // flushed to the device after the next reconnect.
                synchronized (WRITE_LOCK) {
                    WRITE_QUEUE.clear();
                    writing = false;
                }
                if (writeState == WRITE_SENDING) {
                    writeState = WRITE_FAILED;
                    writeMessage = "connection lost before the write completed";
                }
                resetNotify();
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                try {
                    serviceCount = g.getServices().size();
                } catch (Throwable ignored) {
                }
            }
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
            writeStatus = status;
            if (status == BluetoothGatt.GATT_SUCCESS) {
                writeState = WRITE_SUCCESS;
                writeMessage = "wrote " + lastWriteLength + " byte(s) successfully";
            } else {
                writeState = WRITE_FAILED;
                writeMessage = "GATT write failed, status=" + status;
            }
            synchronized (WRITE_LOCK) {
                writing = false;
            }
            // One GATT operation at a time: send the next one only after
            // this one reported back.
            pumpWrites();
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor descriptor, int status) {
            if (CCCD_UUID.equals(descriptor.getUuid())) {
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    notifyState = NOTIFY_SUBSCRIBED;
                    notifyMessage = "subscribed to " + notifyTarget;
                } else {
                    notifyState = NOTIFY_FAILED;
                    notifyMessage = "CCCD write failed, status=" + status;
                }
            }
            synchronized (WRITE_LOCK) {
                writing = false;
            }
            pumpWrites();
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            // Deprecated since API 33 but still invoked; the new overload below
            // is the one used on Android 13+. Both are overridden on purpose.
            byte[] value = null;
            try {
                value = c.getValue();
            } catch (Throwable ignored) {
            }
            storeReceived(value);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c,
                                            byte[] value) {
            storeReceived(value);
        }
    };

    public static void connect(Context ctx, String address) {
        if (address == null || address.isEmpty()) {
            connState = CONN_FAILED;
            return;
        }
        BluetoothAdapter adapter = getAdapter(ctx);
        if (adapter == null) {
            connState = CONN_FAILED;
            return;
        }
        try {
            BluetoothDevice device = adapter.getRemoteDevice(address);
            connAddress = address;
            serviceCount = 0;
            connState = CONN_CONNECTING;
            gatt = device.connectGatt(ctx, false, GATT_CALLBACK);
            if (gatt == null) {
                connState = CONN_FAILED;
            }
        } catch (Throwable t) {
            Log.w(TAG, "connect: " + t);
            connState = CONN_FAILED;
        }
    }

    public static void disconnect() {
        stopScan();
        try {
            if (gatt != null) {
                gatt.disconnect();
                gatt.close();
            }
        } catch (Throwable ignored) {
        }
        gatt = null;
        connState = CONN_DISCONNECTED;
        serviceCount = 0;
        resetWrites();
        resetNotify();
    }

    // ------------------------------------------------------------------
    // GATT write (command downlink)
    //
    // Android's GATT layer allows only ONE outstanding operation at a time,
    // so writes are queued here and the next command is pumped out from
    // onCharacteristicWrite(). This is also the reason all of this has to
    // live in Java: PyJNIus cannot subclass the abstract BluetoothGattCallback.
    // ------------------------------------------------------------------
    public static final int WRITE_IDLE = 0;
    public static final int WRITE_SENDING = 1;
    public static final int WRITE_SUCCESS = 2;
    public static final int WRITE_FAILED = 3;

    /** Payload limit for a single write without MTU negotiation: MTU 23 - 3. */
    public static final int DEFAULT_MAX_PAYLOAD = 20;
    private static final int MAX_PENDING_WRITES = 8;

    private static final Object WRITE_LOCK = new Object();
    private static final Queue<WriteRequest> WRITE_QUEUE = new LinkedList<WriteRequest>();

    private static volatile int writeState = WRITE_IDLE;
    private static volatile int writeStatus = 0;
    private static volatile int lastWriteLength = 0;
    private static volatile String writeMessage = "";
    private static volatile String lastWriteTarget = "";
    private static boolean writing = false;

    private static final class WriteRequest {
        final BluetoothGattCharacteristic characteristic;
        final byte[] data;

        WriteRequest(BluetoothGattCharacteristic characteristic, byte[] data) {
            this.characteristic = characteristic;
            this.data = data;
        }
    }

    /**
     * Queues a command. The payload is passed as a hex string (e.g. "AA55010001")
     * because it marshals reliably through PyJNIus, unlike a raw byte[].
     *
     * @param autoPick when the configured UUID is not found (or empty), fall back to
     *                 the first writable characteristic of the device. Handy during
     *                 bring-up; the UUID that was actually used is reported back via
     *                 getLastWriteTarget().
     * @return an empty string when the command was accepted, otherwise the reason.
     */
    public static String writeCommand(String serviceUuid, String charUuid, String hexData,
                                      boolean autoPick) {
        byte[] data = hexToBytes(hexData);
        if (data == null || data.length == 0) {
            return "command payload is empty or not valid hex";
        }
        if (data.length > DEFAULT_MAX_PAYLOAD) {
            return "command is " + data.length + " bytes, over the " + DEFAULT_MAX_PAYLOAD
                    + "-byte limit of a single write (MTU negotiation is not implemented yet)";
        }
        if (gatt == null || connState != CONN_CONNECTED) {
            return "device is not connected";
        }
        BluetoothGattCharacteristic characteristic = findCharacteristic(serviceUuid, charUuid);
        if (characteristic == null && autoPick) {
            characteristic = findFirstWritable();
        }
        if (characteristic == null) {
            return "characteristic not found - check the UUID (use the services list)";
        }
        if (!isWritable(characteristic)) {
            return "characteristic is not writable, properties=" + propertiesText(characteristic);
        }
        lastWriteTarget = characteristic.getUuid().toString();
        synchronized (WRITE_LOCK) {
            if (WRITE_QUEUE.size() >= MAX_PENDING_WRITES) {
                return "too many pending commands, please retry";
            }
            WRITE_QUEUE.add(new WriteRequest(characteristic, data));
        }
        pumpWrites();
        return "";
    }

    /** UUID that the most recent accepted command was sent to. */
    public static String getLastWriteTarget() {
        return lastWriteTarget == null ? "" : lastWriteTarget;
    }

    public static int getWriteState() {
        return writeState;
    }

    public static int getWriteStatus() {
        return writeStatus;
    }

    public static String getWriteMessage() {
        return writeMessage == null ? "" : writeMessage;
    }

    /** Clears the queue and the last result (used after a client-side timeout). */
    public static void resetWrites() {
        synchronized (WRITE_LOCK) {
            WRITE_QUEUE.clear();
            writing = false;
        }
        writeState = WRITE_IDLE;
        writeStatus = 0;
        writeMessage = "";
    }

    private static void pumpWrites() {
        final WriteRequest request;
        synchronized (WRITE_LOCK) {
            if (writing) {
                return;
            }
            request = WRITE_QUEUE.poll();
            if (request == null) {
                if (writeState == WRITE_SENDING) {
                    writeState = WRITE_IDLE;
                }
                return;
            }
            writing = true;
        }

        BluetoothGatt g = gatt;
        boolean started = false;
        String failure = "";
        if (g == null) {
            failure = "device is not connected";
        } else {
            try {
                request.characteristic.setWriteType(
                        BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                request.characteristic.setValue(request.data);
                started = g.writeCharacteristic(request.characteristic);
                if (!started) {
                    failure = "writeCharacteristic() was rejected by the system";
                }
            } catch (Throwable t) {
                failure = "write threw: " + t;
            }
        }

        lastWriteLength = request.data.length;
        if (!started) {
            synchronized (WRITE_LOCK) {
                writing = false;
            }
            writeState = WRITE_FAILED;
            writeMessage = failure;
            pumpWrites();
            return;
        }
        writeState = WRITE_SENDING;
        writeStatus = 0;
        writeMessage = "";
    }

    private static BluetoothGattCharacteristic findCharacteristic(String serviceUuid, String charUuid) {
        BluetoothGatt g = gatt;
        if (g == null || charUuid == null || charUuid.isEmpty()) {
            return null;
        }
        try {
            for (BluetoothGattService service : g.getServices()) {
                if (serviceUuid != null && !serviceUuid.isEmpty()
                        && !service.getUuid().toString().equalsIgnoreCase(serviceUuid)) {
                    continue;
                }
                for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                    if (c.getUuid().toString().equalsIgnoreCase(charUuid)) {
                        return c;
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "findCharacteristic: " + t);
        }
        return null;
    }

    /** First writable characteristic found on the device (bring-up fallback). */
    private static BluetoothGattCharacteristic findFirstWritable() {
        BluetoothGatt g = gatt;
        if (g == null) {
            return null;
        }
        try {
            for (BluetoothGattService service : g.getServices()) {
                for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                    if (isWritable(c)) {
                        return c;
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "findFirstWritable: " + t);
        }
        return null;
    }

    private static boolean isWritable(BluetoothGattCharacteristic c) {
        int properties = c.getProperties();
        return (properties & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
                || (properties & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0;
    }

    private static String propertiesText(BluetoothGattCharacteristic c) {
        int properties = c.getProperties();
        StringBuilder text = new StringBuilder();
        if ((properties & BluetoothGattCharacteristic.PROPERTY_READ) != 0) {
            text.append("READ ");
        }
        if ((properties & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0) {
            text.append("WRITE ");
        }
        if ((properties & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0) {
            text.append("WRITE_NO_RESPONSE ");
        }
        if ((properties & BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0) {
            text.append("NOTIFY ");
        }
        if ((properties & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0) {
            text.append("INDICATE ");
        }
        String result = text.toString().trim();
        return result.isEmpty() ? "NONE" : result;
    }

    /**
     * Lists the discovered GATT tree as "serviceUuid|characteristicUuid|properties".
     * Service-only rows have an empty middle field. Lets the user find the right
     * UUIDs from the phone without a BLE debugging tool.
     */
    public static String[] getServicesInfo() {
        BluetoothGatt g = gatt;
        if (g == null) {
            return new String[0];
        }
        List<String> rows = new ArrayList<String>();
        try {
            for (BluetoothGattService service : g.getServices()) {
                String serviceUuid = service.getUuid().toString();
                rows.add(serviceUuid + "||service");
                for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                    rows.add(serviceUuid + "|" + c.getUuid().toString() + "|"
                            + propertiesText(c));
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "getServicesInfo: " + t);
        }
        return rows.toArray(new String[0]);
    }

    // ------------------------------------------------------------------
    // GATT notify (uplink: device -> phone)
    //
    // Subscribing needs a CCCD (0x2902) descriptor write, which is another
    // asynchronous GATT operation - hence the same serialization rule as
    // the write queue above. Received bytes are buffered as hex strings and
    // drained by Python, which owns the frame reassembly logic.
    // ------------------------------------------------------------------
    public static final int NOTIFY_OFF = 0;
    public static final int NOTIFY_SUBSCRIBING = 1;
    public static final int NOTIFY_SUBSCRIBED = 2;
    public static final int NOTIFY_FAILED = 3;

    private static final java.util.UUID CCCD_UUID =
            java.util.UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final int MAX_RECEIVED_CHUNKS = 64;

    private static final Object RECEIVE_LOCK = new Object();
    private static final Queue<String> RECEIVED = new LinkedList<String>();

    private static volatile int notifyState = NOTIFY_OFF;
    private static volatile String notifyMessage = "";
    private static volatile String notifyTarget = "";
    private static volatile int receivedChunks = 0;
    private static volatile int receivedDropped = 0;

    /**
     * Subscribes to the notification characteristic (idempotent).
     *
     * @param autoPick fall back to the first notifiable characteristic when the
     *                 configured UUID is empty or not found.
     * @return an empty string when the subscription was started or already active,
     *         otherwise the reason (usually "busy", which the caller retries).
     */
    public static String enableNotify(String serviceUuid, String charUuid, boolean autoPick) {
        BluetoothGatt g = gatt;
        if (g == null || connState != CONN_CONNECTED) {
            return "device is not connected";
        }
        if (notifyState == NOTIFY_SUBSCRIBED) {
            return "";
        }
        BluetoothGattCharacteristic characteristic = findCharacteristic(serviceUuid, charUuid);
        if (characteristic == null && autoPick) {
            characteristic = findFirstNotifiable();
        }
        if (characteristic == null) {
            return "no notifiable characteristic found - check the UUID";
        }
        int properties = characteristic.getProperties();
        boolean indicate = (properties & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0;
        if (!indicate && (properties & BluetoothGattCharacteristic.PROPERTY_NOTIFY) == 0) {
            return "characteristic does not support notify, properties="
                    + propertiesText(characteristic);
        }

        synchronized (WRITE_LOCK) {
            if (writing) {
                // A descriptor write is a GATT operation too: wait for the current one
                return "busy with another GATT operation, will retry";
            }
            try {
                if (!g.setCharacteristicNotification(characteristic, true)) {
                    notifyState = NOTIFY_FAILED;
                    notifyMessage = "setCharacteristicNotification() failed";
                    return notifyMessage;
                }
                BluetoothGattDescriptor cccd = characteristic.getDescriptor(CCCD_UUID);
                if (cccd == null) {
                    // Some devices omit the CCCD; the local subscription is enough
                    notifyTarget = characteristic.getUuid().toString();
                    notifyState = NOTIFY_SUBSCRIBED;
                    notifyMessage = "subscribed locally (the device has no CCCD descriptor)";
                    return "";
                }
                cccd.setValue(indicate ? BluetoothGattDescriptor.ENABLE_INDICATION_VALUE
                                       : BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                if (!g.writeDescriptor(cccd)) {
                    notifyState = NOTIFY_FAILED;
                    notifyMessage = "writeDescriptor() was rejected by the system";
                    return notifyMessage;
                }
                writing = true;      // released in onDescriptorWrite()
            } catch (Throwable t) {
                Log.w(TAG, "enableNotify: " + t);
                notifyState = NOTIFY_FAILED;
                notifyMessage = "enableNotify threw: " + t;
                return notifyMessage;
            }
        }
        notifyTarget = characteristic.getUuid().toString();
        notifyState = NOTIFY_SUBSCRIBING;
        notifyMessage = "";
        return "";
    }

    public static int getNotifyState() {
        return notifyState;
    }

    public static String getNotifyMessage() {
        return notifyMessage == null ? "" : notifyMessage;
    }

    /** UUID of the characteristic the uplink is subscribed to. */
    public static String getNotifyTarget() {
        return notifyTarget == null ? "" : notifyTarget;
    }

    public static int getReceivedDropped() {
        return receivedDropped;
    }

    /**
     * Drains the received chunks (each one a hex string) and clears the buffer.
     * Python reassembles them into frames.
     */
    public static String[] popReceived() {
        synchronized (RECEIVE_LOCK) {
            if (RECEIVED.isEmpty()) {
                return new String[0];
            }
            String[] out = RECEIVED.toArray(new String[0]);
            RECEIVED.clear();
            return out;
        }
    }

    private static void storeReceived(byte[] value) {
        if (value == null || value.length == 0) {
            return;
        }
        StringBuilder hex = new StringBuilder(value.length * 2);
        for (int i = 0; i < value.length; i++) {
            hex.append(String.format("%02x", value[i] & 0xFF));
        }
        synchronized (RECEIVE_LOCK) {
            if (RECEIVED.size() >= MAX_RECEIVED_CHUNKS) {
                RECEIVED.poll();
                receivedDropped++;
            }
            RECEIVED.add(hex.toString());
        }
        receivedChunks++;
    }

    private static void resetNotify() {
        notifyState = NOTIFY_OFF;
        notifyMessage = "";
        notifyTarget = "";
        synchronized (RECEIVE_LOCK) {
            RECEIVED.clear();
        }
    }

    /** First characteristic that supports notify or indicate (bring-up fallback). */
    private static BluetoothGattCharacteristic findFirstNotifiable() {
        BluetoothGatt g = gatt;
        if (g == null) {
            return null;
        }
        try {
            for (BluetoothGattService service : g.getServices()) {
                for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                    int p = c.getProperties();
                    if ((p & BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                            || (p & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0) {
                        return c;
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "findFirstNotifiable: " + t);
        }
        return null;
    }

    private static byte[] hexToBytes(String hex) {
        if (hex == null) {
            return null;
        }
        String cleaned = hex.replace(" ", "").replace(":", "").replace("-", "").trim();
        if (cleaned.isEmpty() || (cleaned.length() % 2) != 0) {
            return null;
        }
        byte[] out = new byte[cleaned.length() / 2];
        try {
            for (int i = 0; i < out.length; i++) {
                out[i] = (byte) Integer.parseInt(cleaned.substring(i * 2, i * 2 + 2), 16);
            }
        } catch (NumberFormatException e) {
            return null;
        }
        return out;
    }

    public static int getConnState() {
        return connState;
    }

    public static int getConnStatus() {
        return connStatus;
    }

    public static int getServiceCount() {
        return serviceCount;
    }

    public static String getConnectedName() {
        return connName == null ? "" : connName;
    }

    public static String getConnectedAddress() {
        return connAddress == null ? "" : connAddress;
    }
}
